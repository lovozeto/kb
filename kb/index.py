"""Build and query the SQLite FTS5 index over the knowledge bases.

The index is derived data: it is rebuilt automatically whenever the set of Markdown files or
any file's size/mtime changes, so callers never reindex by hand.
"""

import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import date

from kb.parser import parse_markdown, parse_taxonomy, Taxonomy

SKIP_FILES = {"INDEX.md", "TAXONOMY.md", "README.md"}
SKIP_DIRS = {"templates", ".git", "node_modules"}
SCHEMA_VERSION = "1"


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
    return os.environ.get("KB_TODAY") or date.today().isoformat()


def find_project_kbs(root, max_depth=4):
    """{project name: knowledge dir} for every <repo>/.claude/knowledge under root."""
    found = {}
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return found
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, _ in os.walk(root):
        depth = dirpath.count(os.sep) - base_depth
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and d != "node_modules"
                       and (not d.startswith(".") or d == ".claude")]
        if os.path.basename(dirpath) == ".claude" and "knowledge" in os.listdir(dirpath):
            repo = os.path.dirname(dirpath)
            found[os.path.basename(repo)] = os.path.join(dirpath, "knowledge")
            dirnames[:] = []
            continue
        if depth >= max_depth:
            dirnames[:] = []
    return found


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

def _walk_markdown(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fn in sorted(filenames):
            if fn.endswith(".md") and fn not in SKIP_FILES:
                yield os.path.join(dirpath, fn)


def discover():
    """[(abs path, ref, base, project or "", is_raw)] for every indexable file."""
    items = []
    root = kb_root()
    sources = [("", root)] + sorted(find_project_kbs(projects_root()).items())
    for project, kdir in sources:
        if not os.path.isdir(kdir):
            continue
        for path in _walk_markdown(kdir):
            rel = os.path.relpath(path, kdir)[:-3].replace(os.sep, "/")
            parts = rel.split("/")
            base = parts[0] if len(parts) > 1 else parts[0]
            ref = (project + ":" + rel) if project else rel
            items.append((path, ref, base, project, ".raw" in parts))
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
    for path in [i[0] for i in items] + [taxonomy_path]:
        try:
            st = os.stat(path)
            h.update(("%s|%d|%d\n" % (path, st.st_size, int(st.st_mtime_ns))).encode())
        except OSError:
            h.update(("%s|missing\n" % path).encode())
    return h.hexdigest()


def load_taxonomy():
    path = os.path.join(kb_root(), "TAXONOMY.md")
    try:
        with open(path, encoding="utf-8") as f:
            return parse_taxonomy(f.read())
    except OSError:
        return Taxonomy()


# --- build ---------------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, ref TEXT UNIQUE, base TEXT,
  project TEXT, raw INTEGER, tier TEXT, review_by TEXT, last_verified TEXT, publishers TEXT);
CREATE TABLE sections (id INTEGER PRIMARY KEY, file_id INTEGER, anchor TEXT, heading TEXT,
  level INTEGER, start_line INTEGER, end_line INTEGER, tags TEXT);
CREATE TABLE tags (section_id INTEGER, facet TEXT, value TEXT);
CREATE TABLE rules (id INTEGER PRIMARY KEY, section_id INTEGER, text TEXT, source TEXT,
  line INTEGER);
CREATE VIRTUAL TABLE rules_fts USING fts5(text, heading, tagtext, tokenize='unicode61 remove_diacritics 2');
"""


def _prose_rule(lines, section):
    """A section with no bullets is indexed as one rule made of its prose, so prose KBs
    remain findable before they are converted to atomic rules."""
    body = []
    for line in lines[section.start_line:section.end_line]:
        s = line.strip()
        if s and not s.startswith(("#", "<!--")):
            body.append(s)
    return " ".join(body)[:1200]


def parent_heading(doc, section):
    """Heading of the level-2 parent of a level-3 section, else ''."""
    if section.level != 3 or "/" not in section.anchor:
        return ""
    parent_anchor = section.anchor.rsplit("/", 1)[0]
    for s in doc.sections:
        if s.anchor == parent_anchor:
            return s.heading
    return ""


def build(db_path, items, taxonomy):
    tmp = db_path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    for path, ref, base, project, raw in items:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        doc = parse_markdown(text)
        lines = text.splitlines()
        fm = doc.frontmatter
        cur = con.execute(
            "INSERT INTO files (path, ref, base, project, raw, tier, review_by, last_verified,"
            " publishers) VALUES (?,?,?,?,?,?,?,?,?)",
            (path, ref, base, project, int(raw), fm.get("tier", ""), fm.get("review_by", ""),
             fm.get("last_verified", ""), json.dumps(doc.publishers)))
        file_id = cur.lastrowid
        for s in doc.sections:
            sid = con.execute(
                "INSERT INTO sections (file_id, anchor, heading, level, start_line, end_line,"
                " tags) VALUES (?,?,?,?,?,?,?)",
                (file_id, s.anchor, s.heading, s.level, s.start_line, s.end_line,
                 json.dumps(s.tags))).lastrowid
            tagterms = []
            for facet, values in s.tags.items():
                for v in values:
                    con.execute("INSERT INTO tags VALUES (?,?,?)", (sid, facet, v))
                    tagterms.extend(taxonomy.expand([v]) if facet != "keywords" else [v])
            rules = s.rules or ([type("R", (), {"text": _prose_rule(lines, s), "source": "",
                                                "line": s.start_line})()]
                                if _prose_rule(lines, s) else [])
            for r in rules:
                rid = con.execute(
                    "INSERT INTO rules (section_id, text, source, line) VALUES (?,?,?,?)",
                    (sid, r.text, r.source, r.line)).lastrowid
                # Searchable heading = file title › section heading (and its parent).
                heading_path = " › ".join(x for x in (doc.title, parent_heading(doc, s), s.heading) if x)
                con.execute("INSERT INTO rules_fts (rowid, text, heading, tagtext)"
                            " VALUES (?,?,?,?)", (rid, r.text, heading_path, " ".join(tagterms)))
    con.commit()
    con.close()
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    os.replace(tmp, db_path)


def open_index(force=False):
    """Return a connection to an up-to-date index, rebuilding it when anything changed."""
    db_path = default_index_path()
    items = discover()
    taxonomy = load_taxonomy()
    fp = _fingerprint(items, os.path.join(kb_root(), "TAXONOMY.md"))
    current = None
    if not force and os.path.exists(db_path):
        try:
            con = sqlite3.connect(db_path)
            row = con.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()
            current = row[0] if row else None
            con.close()
        except sqlite3.DatabaseError:
            current = None
    if force or current != fp:
        build(db_path, items, taxonomy)
        con = sqlite3.connect(db_path)
        con.execute("INSERT OR REPLACE INTO meta VALUES ('fingerprint', ?)", (fp,))
        con.commit()
        con.close()
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con, taxonomy


# --- query ---------------------------------------------------------------------------------

TOKEN_RE = re.compile(r"[\w.:]+", re.UNICODE)


def _fts_query(text, joiner):
    terms = ['"%s"' % t.replace('"', "") for t in TOKEN_RE.findall(text)]
    return (" %s " % joiner).join(terms)


def search(con, taxonomy, query, bases=(), tags=(), facets=(), tier=None, fresh=False,
           raw=False, projects=None, limit=8):
    """projects: None = global only; a set of project names to include besides global;
    "all" = everything."""
    where, params = [], []
    if not raw:
        where.append("f.raw = 0")
    if projects != "all":
        names = sorted(projects or [])
        where.append("(f.project = ''%s)" % (" OR f.project IN (%s)" % ",".join("?" * len(names))
                                            if names else ""))
        params.extend(names)
    if bases:
        where.append("f.base IN (%s)" % ",".join("?" * len(bases)))
        params.extend(bases)
    if tier:
        where.append("f.tier = ?")
        params.append(tier)
    if fresh:
        where.append("f.review_by > ?")
        params.append(today())
    for t in tags:
        hit = taxonomy.canonical(t)
        value = hit[1] if hit else t
        where.append("EXISTS (SELECT 1 FROM tags g WHERE g.section_id = s.id AND g.value = ?)")
        params.append(value)
    for spec in facets:
        facet, _, value = spec.partition("=")
        hit = taxonomy.canonical(value)
        where.append("EXISTS (SELECT 1 FROM tags g WHERE g.section_id = s.id AND g.facet = ?"
                     " AND g.value = ?)")
        params.extend([facet.strip().lower(), hit[1] if hit else value.strip()])
    extra = (" AND " + " AND ".join(where)) if where else ""
    sql = ("SELECT r.text, r.source, s.anchor, s.heading, s.tags, f.ref, f.tier, f.review_by,"
           " f.project FROM rules_fts JOIN rules r ON r.id = rules_fts.rowid"
           " JOIN sections s ON s.id = r.section_id JOIN files f ON f.id = s.file_id"
           " WHERE rules_fts MATCH ?" + extra + " ORDER BY bm25(rules_fts, 1.0, 2.0, 1.5)"
           " LIMIT ?")
    # Precision first: the exact phrase, then every word (AND), and only if nothing matched,
    # any word (OR). Earlier tiers rank first; later tiers fill the remaining slots.
    tokens = TOKEN_RE.findall(query)
    tiers = []
    if len(tokens) > 1:
        tiers.append('"%s"' % " ".join(t.replace('"', "") for t in tokens))
    tiers.append(_fts_query(query, "AND"))
    rows, seen = [], set()
    for q in tiers:
        if not q or len(rows) >= limit:
            break
        for r in con.execute(sql, [q] + params + [limit]).fetchall():
            key = (r["ref"], r["anchor"], r["text"])
            if key not in seen and len(rows) < limit:
                seen.add(key)
                rows.append(r)
    if not rows and len(tokens) > 1:
        rows = con.execute(sql, [_fts_query(query, "OR")] + params + [limit]).fetchall()
    return [{"ref": "%s#%s" % (r["ref"], r["anchor"]), "heading": r["heading"],
             "text": r["text"], "source": r["source"], "tier": r["tier"],
             "review_by": r["review_by"], "tags": json.loads(r["tags"])} for r in rows]


# --- other commands ------------------------------------------------------------------------

def _scope_sql(projects, alias="f"):
    if projects == "all":
        return "", []
    names = sorted(projects or [])
    if not names:
        return " AND %s.project = ''" % alias, []
    return (" AND (%s.project = '' OR %s.project IN (%s))" % (alias, alias, ",".join("?" * len(names))),
            names)


def get_section(con, ref):
    """(markdown text of one section) or None. ref = 'base/file#anchor' or 'proj:file#anchor'."""
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
        " r.section_id = s.id) AS rules FROM sections s JOIN files f ON f.id = s.file_id"
        " WHERE f.ref = ? ORDER BY s.start_line", (file_ref,)).fetchall()
    return [dict(r) for r in rows]


def facet_counts(con, projects):
    extra, params = _scope_sql(projects)
    rows = con.execute(
        "SELECT g.facet, g.value, COUNT(DISTINCT g.section_id) AS n FROM tags g"
        " JOIN sections s ON s.id = g.section_id JOIN files f ON f.id = s.file_id"
        " WHERE f.raw = 0" + extra + " GROUP BY g.facet, g.value ORDER BY g.facet, n DESC",
        params).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["facet"], {})[r["value"]] = r["n"]
    return out


def stale_files(con, projects):
    extra, params = _scope_sql(projects)
    rows = con.execute("SELECT ref, review_by, last_verified FROM files f WHERE f.raw = 0"
                       " AND (f.review_by = '' OR f.review_by <= ?)" + extra + " ORDER BY ref",
                       [today()] + params).fetchall()
    return [{"ref": r["ref"], "review_by": r["review_by"] or None,
             "last_verified": r["last_verified"] or None,
             "reason": "expired" if r["review_by"] else "no review_by"} for r in rows]


def lint(con, taxonomy):
    """{"errors": [...], "warnings": [...]} across every non-raw file of every project."""
    errors, warnings = [], []
    for f in con.execute("SELECT ref, tier, review_by FROM files WHERE raw = 0 ORDER BY ref"):
        if not f["tier"]:
            warnings.append("%s: no tier in frontmatter" % f["ref"])
        if not f["review_by"]:
            warnings.append("%s: no review_by in frontmatter" % f["ref"])
    sections = con.execute("SELECT s.id, s.anchor, s.tags, f.ref FROM sections s JOIN files f"
                           " ON f.id = s.file_id WHERE f.raw = 0 ORDER BY f.ref, s.start_line")
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
        for r in con.execute("SELECT line, source FROM rules WHERE section_id = ?", (s["id"],)):
            if not r["source"]:
                warnings.append("%s: rule on line %d has no source" % (where, r["line"]))
    return {"errors": errors, "warnings": warnings}
