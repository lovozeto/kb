"""Build and query the SQLite FTS5 index over the knowledge bases.

The index is derived data: it is rebuilt automatically whenever the set of Markdown files,
any file's size/mtime, TAXONOMY.md, or kb's own code changes, so callers never reindex by hand.
"""

import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from typing import NamedTuple

from kb.parser import parse_markdown, parse_taxonomy, Rule, Taxonomy

ROOT_ONLY_FILES = {"INDEX.md", "TAXONOMY.md", "README.md"}   # skipped at a knowledge root
ROOT_ONLY_DIRS = {"templates"}                               # skipped at a knowledge root
NEVER_DIRS = {".git", "node_modules"}
AUTO_FACETS = {"base", "tier", "fresh", "source", "file"}
SCHEMA_VERSION = "2"


class KbError(Exception):
    """A user error (bad filter, unknown ref): reported without a traceback."""


class FileItem(NamedTuple):
    path: str
    ref: str          # "ux/forms" or "<project>:palette"
    base: str         # first folder, or the file stem for files at the root
    project: str      # "" for the global KB
    raw: bool         # under a .raw/ folder


@dataclass
class Scope:
    """Global KB plus some projects, or everything."""
    projects: set = field(default_factory=set)
    everything: bool = False


@dataclass
class Filters:
    bases: list = field(default_factory=list)
    tags: list = field(default_factory=list)        # any facet value or synonym
    facets: list = field(default_factory=list)      # "facet=value"
    tier: str = None
    fresh: bool = False
    raw: bool = False
    scope: Scope = None


# --- locations ---------------------------------------------------------------------------

def default_index_path():
    if os.environ.get("KB_INDEX"):
        return os.environ["KB_INDEX"]
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Caches")
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    return os.path.join(base, "kb", "index.db")


def kb_root():
    return os.path.expanduser(os.environ.get("KB_ROOT", "~/dev/claude-kb"))


def projects_root():
    return os.path.expanduser(os.environ.get("KB_PROJECTS_ROOT", "~/GitHub"))


def today():
    """ISO date; KB_TODAY overrides it (used by tests)."""
    return os.environ.get("KB_TODAY") or date.today().isoformat()


def find_project_kbs(root, max_depth=4):
    """{project name: knowledge dir} for every <repo>/.claude/knowledge under root.

    The name is the repo folder name; when two repos share it, both use their path relative
    to root instead, so they never collide.
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return {}
    found = []
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, _ in os.walk(root):
        if os.path.basename(dirpath) == ".claude":
            if "knowledge" in dirnames:
                found.append((os.path.dirname(dirpath), os.path.join(dirpath, "knowledge")))
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in NEVER_DIRS
                       and (not d.startswith(".") or d == ".claude")]
        if dirpath.count(os.sep) - base_depth >= max_depth:
            dirnames[:] = [d for d in dirnames if d == ".claude"]
    counts = {}
    for repo, _ in found:
        counts[os.path.basename(repo)] = counts.get(os.path.basename(repo), 0) + 1
    names = {}
    for repo, kdir in found:
        name = os.path.basename(repo)
        if counts[name] > 1:
            name = os.path.relpath(repo, root).replace(os.sep, "/")
        names[name] = kdir
    return names


def current_project(cwd, projects):
    """Name of the project whose repo contains cwd, if it has a knowledge base."""
    cwd = os.path.realpath(cwd)
    best = None
    for name, kdir in projects.items():
        repo = os.path.realpath(os.path.dirname(os.path.dirname(kdir)))
        if cwd == repo or cwd.startswith(repo + os.sep):
            if best is None or len(repo) > len(best[1]):
                best = (name, repo)
    return best[0] if best else None


# --- discovery ----------------------------------------------------------------------------

def _walk_markdown(kdir):
    for dirpath, dirnames, filenames in os.walk(kdir):
        at_root = os.path.abspath(dirpath) == os.path.abspath(kdir)
        dirnames[:] = sorted(d for d in dirnames if d not in NEVER_DIRS
                             and not (at_root and d in ROOT_ONLY_DIRS))
        for fn in sorted(filenames):
            if fn.endswith(".md") and not (at_root and fn in ROOT_ONLY_FILES):
                yield os.path.join(dirpath, fn)


def discover():
    """Every indexable file of the global KB and of every project KB."""
    items = []
    sources = [("", kb_root())] + sorted(find_project_kbs(projects_root()).items())
    for project, kdir in sources:
        if not os.path.isdir(kdir):
            continue
        for path in _walk_markdown(kdir):
            rel = os.path.relpath(path, kdir)[:-3].replace(os.sep, "/")
            parts = rel.split("/")
            items.append(FileItem(path=path, ref=(project + ":" + rel) if project else rel,
                                  base=parts[0], project=project, raw=".raw" in parts))
    return items


def _code_digest():
    """Hash of kb's own source, so an index built by older code is rebuilt after an update."""
    h = hashlib.sha256()
    here = os.path.dirname(os.path.abspath(__file__))
    for fn in sorted(os.listdir(here)):
        if fn.endswith(".py"):
            with open(os.path.join(here, fn), "rb") as f:
                h.update(f.read())
    return h.hexdigest()


def _fingerprint(items, taxonomy_path):
    h = hashlib.sha256((SCHEMA_VERSION + _code_digest()).encode())
    for path in [i.path for i in items] + [taxonomy_path]:
        try:
            st = os.stat(path)
            h.update(("%s|%d|%d\n" % (path, st.st_size, int(st.st_mtime_ns))).encode())
        except OSError:
            h.update(("%s|missing\n" % path).encode())
    return h.hexdigest()


def load_taxonomy():
    try:
        with open(os.path.join(kb_root(), "TAXONOMY.md"), encoding="utf-8") as f:
            return parse_taxonomy(f.read())
    except OSError:
        return Taxonomy()


# --- build ---------------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, ref TEXT UNIQUE, base TEXT,
  project TEXT, raw INTEGER, tier TEXT, review_by TEXT, last_verified TEXT);
CREATE TABLE file_sources (file_id INTEGER, publisher TEXT);
CREATE TABLE sections (id INTEGER PRIMARY KEY, file_id INTEGER, anchor TEXT, heading TEXT,
  level INTEGER, start_line INTEGER, end_line INTEGER, tags TEXT);
CREATE TABLE tags (section_id INTEGER, facet TEXT, value TEXT);
CREATE TABLE rules (id INTEGER PRIMARY KEY, section_id INTEGER, text TEXT, source TEXT,
  line INTEGER, prose INTEGER);
CREATE VIRTUAL TABLE rules_fts USING fts5(text, heading, tagtext,
  tokenize='unicode61 remove_diacritics 2');
"""


def _index_file(con, item, taxonomy):
    try:
        with open(item.path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return
    doc = parse_markdown(text)
    lines = text.splitlines()
    fm = doc.frontmatter
    file_id = con.execute(
        "INSERT INTO files (path, ref, base, project, raw, tier, review_by, last_verified)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (item.path, item.ref, item.base, item.project, int(item.raw), fm.get("tier", ""),
         fm.get("review_by", ""), fm.get("last_verified", ""))).lastrowid
    for publisher in doc.publishers:
        con.execute("INSERT INTO file_sources VALUES (?,?)", (file_id, publisher))
    for s in doc.sections:
        section_id = con.execute(
            "INSERT INTO sections (file_id, anchor, heading, level, start_line, end_line, tags)"
            " VALUES (?,?,?,?,?,?,?)", (file_id, s.anchor, s.heading, s.level, s.start_line,
                                        s.end_line, json.dumps(s.tags))).lastrowid
        tag_terms = []
        for facet, values in s.tags.items():
            for v in values:
                con.execute("INSERT INTO tags VALUES (?,?,?)", (section_id, facet, v))
                tag_terms.extend([v] if facet == "keywords" else taxonomy.expand([v]))
        rules, prose = s.rules, False
        if not rules:
            body = doc.prose_of(s, lines)
            rules, prose = ([Rule(text=body, line=s.start_line)] if body else []), True
        parent = doc.parent_of(s)
        heading_path = " › ".join(x for x in (doc.title, parent.heading if parent else "",
                                                s.heading) if x)
        for r in rules:
            rule_id = con.execute(
                "INSERT INTO rules (section_id, text, source, line, prose) VALUES (?,?,?,?,?)",
                (section_id, r.text, r.source, r.line, int(prose))).lastrowid
            con.execute("INSERT INTO rules_fts (rowid, text, heading, tagtext) VALUES (?,?,?,?)",
                        (rule_id, r.text, heading_path, " ".join(tag_terms)))


def build(db_path, items, taxonomy, fingerprint):
    """Write a fresh index to a private temp file, then swap it in atomically, so parallel
    runs never see or produce a half-written index."""
    folder = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".kb-", suffix=".db", dir=folder)
    os.close(fd)
    try:
        con = sqlite3.connect(tmp)
        con.executescript(SCHEMA)
        for item in items:
            _index_file(con, item, taxonomy)
        con.execute("INSERT INTO meta VALUES ('fingerprint', ?)", (fingerprint,))
        con.commit()
        con.close()
        os.replace(tmp, db_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _stored_fingerprint(db_path):
    try:
        con = sqlite3.connect(db_path)
        row = con.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()
        con.close()
        return row[0] if row else None
    except sqlite3.DatabaseError:
        return None


def open_index(force=False):
    """Return (connection to an up-to-date index, taxonomy)."""
    if not os.path.isdir(kb_root()):
        raise KbError("no KB at %s (set KB_ROOT to the knowledge folder)" % kb_root())
    db_path = default_index_path()
    items = discover()
    taxonomy = load_taxonomy()
    fingerprint = _fingerprint(items, os.path.join(kb_root(), "TAXONOMY.md"))
    if force or not os.path.exists(db_path) or _stored_fingerprint(db_path) != fingerprint:
        build(db_path, items, taxonomy, fingerprint)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con, taxonomy


# --- shared SQL pieces ---------------------------------------------------------------------

def _scope_sql(scope, alias="f"):
    if scope is None or scope.everything:
        return "", []
    names = sorted(scope.projects)
    if not names:
        return " AND %s.project = ''" % alias, []
    return (" AND (%s.project = '' OR %s.project IN (%s))"
            % (alias, alias, ",".join("?" * len(names))), names)


def _facet_sql(facet, value, taxonomy):
    """SQL condition (on aliases s, f) for one facet=value, automatic or tagged."""
    facet = facet.strip().lower()
    value = value.strip()
    if facet == "base":
        return "f.base = ?", [value]
    if facet == "tier":
        return "f.tier = ?", [value]
    if facet == "file":
        return "f.ref = ?", [value]
    if facet == "source":
        return ("EXISTS (SELECT 1 FROM file_sources fs WHERE fs.file_id = f.id"
                " AND fs.publisher = ?)", [value])
    if facet == "fresh":
        conditions = {"fresh": "f.review_by > ?",
                      "expired": "(f.review_by != '' AND f.review_by <= ?)",
                      "unknown": "(f.review_by = '' AND ? IS NOT NULL)"}
        if value not in conditions:
            raise KbError("fresh takes fresh, expired, or unknown")
        return conditions[value], [today()]
    if facet != "keywords" and facet not in taxonomy.facets:
        known = sorted(AUTO_FACETS | set(taxonomy.facets) | {"keywords"})
        raise KbError("unknown facet '%s' (known: %s)" % (facet, ", ".join(known)))
    hit = taxonomy.canonical(value)
    return ("EXISTS (SELECT 1 FROM tags g WHERE g.section_id = s.id AND g.facet = ?"
            " AND g.value = ?)", [facet, hit[1] if hit and hit[0] == facet else value])


# --- search --------------------------------------------------------------------------------

TOKEN_RE = re.compile(r"[\w.:]+", re.UNICODE)
TEXT_COLUMNS = "{text heading} : "


def _quote(term):
    return '"%s"' % term.replace('"', "")


def _term_group(token, taxonomy):
    """A token OR'd with its synonym ring, so a synonym reaches rules that use another word."""
    variants = taxonomy.expand([token])
    if len(variants) == 1:
        return _quote(token)
    return "(" + " OR ".join(_quote(v) for v in variants) + ")"


def _match_expressions(query, taxonomy):
    """FTS expressions from strictest to loosest: exact phrase, then every word; plus the
    any-word fallback used only when nothing stricter matched."""
    tokens = TOKEN_RE.findall(query)
    if not tokens:
        return [], ""
    strict = []
    if len(tokens) > 1:
        strict.append(_quote(" ".join(tokens)))
    strict.append(" AND ".join(_term_group(t, taxonomy) for t in tokens))
    # Each level first in the rule's own words, then also in its tags: a rule that says the
    # word (or a synonym) ranks before rules that only carry the matching tag.
    strict = [e for expression in strict for e in (TEXT_COLUMNS + expression, expression)]
    fallback = " OR ".join(_term_group(t, taxonomy) for t in tokens) if len(tokens) > 1 else ""
    return strict, fallback


def search(con, taxonomy, query, filters, limit=8):
    where, params = [], []
    if not filters.raw:
        where.append("f.raw = 0")
    if filters.bases:
        where.append("f.base IN (%s)" % ",".join("?" * len(filters.bases)))
        params.extend(filters.bases)
    if filters.tier:
        where.append("f.tier = ?")
        params.append(filters.tier)
    if filters.fresh:
        where.append("f.review_by > ?")
        params.append(today())
    for tag in filters.tags:
        hit = taxonomy.canonical(tag)
        where.append("EXISTS (SELECT 1 FROM tags g WHERE g.section_id = s.id AND g.value = ?)")
        params.append(hit[1] if hit else tag)
    for spec in filters.facets:
        facet, sep, value = spec.partition("=")
        if not sep:
            raise KbError("--facet takes facet=value, got '%s'" % spec)
        condition, condition_params = _facet_sql(facet, value, taxonomy)
        where.append(condition)
        params.extend(condition_params)
    scope_sql, scope_params = _scope_sql(filters.scope)
    sql = ("SELECT r.text, r.source, r.prose, s.anchor, s.heading, s.tags, f.ref, f.tier,"
           " f.review_by FROM rules_fts JOIN rules r ON r.id = rules_fts.rowid"
           " JOIN sections s ON s.id = r.section_id JOIN files f ON f.id = s.file_id"
           " WHERE rules_fts MATCH ?" + "".join(" AND " + w for w in where) + scope_sql +
           " ORDER BY bm25(rules_fts, 1.0, 2.0, 1.5) LIMIT ?")
    bind = params + scope_params
    strict, fallback = _match_expressions(query, taxonomy)
    if not strict:
        raise KbError("empty query: give at least one word to search for")
    rows, seen = [], set()
    for expression in strict:               # stricter matches rank first, looser ones fill
        if len(rows) >= limit:
            break
        for r in con.execute(sql, [expression] + bind + [limit]).fetchall():
            key = (r["ref"], r["anchor"], r["text"])
            if key not in seen and len(rows) < limit:
                seen.add(key)
                rows.append(r)
    if not rows and fallback:
        rows = con.execute(sql, [fallback] + bind + [limit]).fetchall()
    return [{"ref": "%s#%s" % (r["ref"], r["anchor"]), "heading": r["heading"],
             "text": r["text"], "source": r["source"], "prose": bool(r["prose"]),
             "tier": r["tier"], "review_by": r["review_by"], "tags": json.loads(r["tags"])}
            for r in rows]


# --- other commands ------------------------------------------------------------------------

def get_section(con, ref):
    """Markdown text of one section, or None. ref = 'base/file#anchor' or 'proj:file#anchor'."""
    file_ref, _, anchor = ref.partition("#")
    row = con.execute("SELECT f.path, s.start_line, s.end_line FROM sections s JOIN files f"
                      " ON f.id = s.file_id WHERE f.ref = ? AND s.anchor = ?",
                      (file_ref, anchor)).fetchone()
    if not row:
        return None
    with open(row["path"], encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    return "\n".join(lines[row["start_line"] - 1:row["end_line"]]).rstrip() + "\n"


def outline(con, file_ref):
    rows = con.execute(
        "SELECT s.anchor, s.heading, s.level, (SELECT COUNT(*) FROM rules r WHERE"
        " r.section_id = s.id AND r.prose = 0) AS rules FROM sections s JOIN files f"
        " ON f.id = s.file_id WHERE f.ref = ? ORDER BY s.start_line", (file_ref,)).fetchall()
    return [dict(r) for r in rows]


def facet_counts(con, scope):
    """{facet: {value: number of sections}} for tagged and automatic facets."""
    scope_sql, params = _scope_sql(scope)
    sections_in_scope = (" FROM sections s JOIN files f ON f.id = s.file_id WHERE f.raw = 0"
                         + scope_sql)
    out = {}

    def add(facet, rows):
        for value, n in rows:
            if value:
                out.setdefault(facet, {})[value] = n

    add("base", con.execute("SELECT f.base, COUNT(*)" + sections_in_scope + " GROUP BY f.base",
                            params))
    add("tier", con.execute("SELECT f.tier, COUNT(*)" + sections_in_scope + " GROUP BY f.tier",
                            params))
    add("fresh", con.execute(
        "SELECT CASE WHEN f.review_by = '' THEN 'unknown' WHEN f.review_by > ? THEN 'fresh'"
        " ELSE 'expired' END AS v, COUNT(*)" + sections_in_scope + " GROUP BY v",
        [today()] + params))
    add("source", con.execute(
        "SELECT fs.publisher, COUNT(*) FROM sections s JOIN files f ON f.id = s.file_id"
        " JOIN file_sources fs ON fs.file_id = f.id WHERE f.raw = 0" + scope_sql +
        " GROUP BY fs.publisher", params))
    for facet, value, n in con.execute(
            "SELECT g.facet, g.value, COUNT(DISTINCT g.section_id) FROM tags g"
            " JOIN sections s ON s.id = g.section_id JOIN files f ON f.id = s.file_id"
            " WHERE f.raw = 0" + scope_sql + " GROUP BY g.facet, g.value", params):
        out.setdefault(facet, {})[value] = n
    return {facet: dict(sorted(values.items(), key=lambda kv: -kv[1]))
            for facet, values in out.items()}


def stale_files(con, scope):
    scope_sql, params = _scope_sql(scope)
    rows = con.execute("SELECT ref, review_by, last_verified FROM files f WHERE f.raw = 0"
                       " AND (f.review_by = '' OR f.review_by <= ?)" + scope_sql +
                       " ORDER BY ref", [today()] + params).fetchall()
    return [{"ref": r["ref"], "review_by": r["review_by"] or None,
             "last_verified": r["last_verified"] or None,
             "reason": "expired" if r["review_by"] else "no review_by"} for r in rows]


def lint(con, taxonomy, scope):
    """{"errors": [...], "warnings": [...]} for the files in scope (raw sources excluded)."""
    scope_sql, params = _scope_sql(scope)
    errors, warnings = [], []
    for f in con.execute("SELECT ref, tier, review_by FROM files f WHERE f.raw = 0" + scope_sql
                         + " ORDER BY ref", params):
        if not f["tier"]:
            warnings.append("%s: no tier in frontmatter" % f["ref"])
        if not f["review_by"]:
            warnings.append("%s: no review_by in frontmatter" % f["ref"])
    sections = con.execute("SELECT s.id, s.anchor, s.tags, f.ref FROM sections s JOIN files f"
                           " ON f.id = s.file_id WHERE f.raw = 0" + scope_sql +
                           " ORDER BY f.ref, s.start_line", params).fetchall()
    for s in sections:
        where = "%s#%s" % (s["ref"], s["anchor"])
        tags = json.loads(s["tags"])
        if not tags:
            warnings.append("%s: section has no tags" % where)
        for facet, values in tags.items():
            if facet == "keywords":
                continue
            if facet not in taxonomy.facets:
                errors.append("%s: unknown facet '%s' (not in TAXONOMY.md)" % (where, facet))
                continue
            for v in values:
                if v in taxonomy.facets[facet]:
                    continue
                hit = taxonomy.canonical(v)
                hint = (" — use '%s'" % hit[1]) if hit and hit[0] == facet else ""
                errors.append("%s: '%s' is not a %s value%s" % (where, v, facet, hint))
        for r in con.execute("SELECT line, source, prose FROM rules WHERE section_id = ?",
                             (s["id"],)):
            if r["prose"]:
                warnings.append("%s: prose, not atomic rules (convert to bullets)" % where)
            elif not r["source"]:
                warnings.append("%s: rule on line %d has no source" % (where, r["line"]))
    return {"errors": errors, "warnings": warnings}
