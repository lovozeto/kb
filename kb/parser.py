"""Parse knowledge-base Markdown into sections, rules, and tags.

Format (see README):
- optional YAML-like frontmatter between `---` lines (top-level scalars, `sources` list);
- `##` / `###` headings start sections; a `<!-- tags: facet=v1,v2; facet=v -->` line right
  under a heading tags that section, and child sections inherit their parent's tags;
- a rule is a `- ` bullet (continuation lines indented), ending in an optional `[source]`.
"""

import re
from dataclasses import dataclass, field

HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
TAGS_RE = re.compile(r"^<!--\s*tags:\s*(.*?)\s*-->\s*$")
SOURCE_RE = re.compile(r"\s*\[([^\[\]]+)\]\s*$")
SCALAR_RE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*?)\s*$")
PUBLISHER_RE = re.compile(r"^\s*-?\s*publisher:\s*(.+?)\s*$")


@dataclass
class Rule:
    text: str
    source: str = ""
    line: int = 0


@dataclass
class Section:
    heading: str
    anchor: str
    level: int
    start_line: int
    end_line: int = 0
    tags: dict = field(default_factory=dict)
    rules: list = field(default_factory=list)


@dataclass
class Document:
    frontmatter: dict
    publishers: list
    sections: list
    title: str = ""

    def parent_of(self, section):
        """The level-2 section a level-3 section belongs to, else None."""
        if section.level != 3 or "/" not in section.anchor:
            return None
        parent_anchor = section.anchor.rsplit("/", 1)[0]
        return next((s for s in self.sections if s.anchor == parent_anchor), None)

    def prose_of(self, section, lines):
        """A section's non-heading, non-tag text joined into one line (for prose KBs)."""
        body = [ln.strip() for ln in lines[section.start_line:section.end_line]
                if ln.strip() and not ln.strip().startswith(("#", "<!--"))]
        return " ".join(body)[:1200]


def slugify(text):
    slug = re.sub(r"[^\w\s-]", "", text.lower(), flags=re.UNICODE)
    return re.sub(r"[\s_]+", "-", slug).strip("-")


def parse_tags(spec):
    """`topic=forms,validation; platform=web` -> {"topic": [...], "platform": [...]}"""
    tags = {}
    for part in spec.split(";"):
        if "=" not in part:
            continue
        facet, values = part.split("=", 1)
        facet = facet.strip().lower()
        vals = [v.strip() for v in values.split(",") if v.strip()]
        if facet and vals:
            tags.setdefault(facet, [])
            tags[facet].extend(v for v in vals if v not in tags[facet])
    return tags


def _merge(parent, own):
    merged = {k: list(v) for k, v in parent.items()}
    for facet, vals in own.items():
        merged.setdefault(facet, [])
        merged[facet].extend(v for v in vals if v not in merged[facet])
    return merged


def _split_frontmatter(lines):
    if not lines or lines[0].strip() != "---":
        return {}, [], 0
    front, publishers = {}, []
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            return front, publishers, i + 1
        m = PUBLISHER_RE.match(line)
        if m:
            publishers.append(m.group(1).strip().strip("\"'"))
            continue
        if not line.startswith((" ", "\t", "-")):
            m = SCALAR_RE.match(line)
            if m and m.group(2):
                front[m.group(1)] = m.group(2).strip().strip("\"'")
    return {}, [], 0  # unterminated frontmatter: treat the file as body only


def _make_rule(parts, line_no):
    text = " ".join(p.strip() for p in parts).strip()
    source = ""
    m = SOURCE_RE.search(text)
    if m:
        source = m.group(1).strip()
        text = text[: m.start()].rstrip()
    return Rule(text=text, source=source, line=line_no)


def parse_markdown(text):
    lines = text.splitlines()
    front, publishers, body_start = _split_frontmatter(lines)
    sections = []
    parent = None          # last level-2 section, for anchors and tag inheritance
    current = None
    rule_parts, rule_line = None, 0
    seen = {}
    title = ""

    def flush_rule():
        nonlocal rule_parts
        if rule_parts is not None and current is not None:
            current.rules.append(_make_rule(rule_parts, rule_line))
        rule_parts = None

    for idx in range(body_start, len(lines)):
        line, line_no = lines[idx], idx + 1
        m = HEADING_RE.match(line)
        if m:
            flush_rule()
            if current is not None:
                current.end_line = line_no - 1
            level, heading = len(m.group(1)), m.group(2)
            slug = slugify(heading)
            if level == 3 and parent is not None:
                anchor = parent.anchor + "/" + slug
                tags = _merge(parent.tags, {})
            else:
                anchor, tags = slug, {}
            count = seen.get(anchor, 0)
            seen[anchor] = count + 1
            if count:
                anchor = "%s-%d" % (anchor, count + 1)
            current = Section(heading=heading, anchor=anchor, level=level,
                              start_line=line_no, tags=tags)
            sections.append(current)
            if level == 2:
                parent = current
            continue
        if not title and current is None and line.startswith("# "):
            title = line[2:].strip()
            continue
        if current is None:
            continue
        t = TAGS_RE.match(line.strip())
        if t:
            current.tags = _merge(current.tags, parse_tags(t.group(1)))
            continue
        if line.startswith("- "):
            flush_rule()
            rule_parts, rule_line = [line[2:]], line_no
        elif rule_parts is not None and line.startswith((" ", "\t")) and line.strip():
            rule_parts.append(line)
        else:
            flush_rule()

    flush_rule()
    if current is not None:
        current.end_line = len(lines)
    return Document(frontmatter=front, publishers=publishers, sections=sections, title=title)


@dataclass
class Taxonomy:
    """Closed vocabulary: facet -> canonical values, each with a synonym ring."""
    facets: dict = field(default_factory=dict)       # facet -> [canonical values]
    rings: dict = field(default_factory=dict)        # (facet, value) -> [synonyms]
    _lookup: dict = field(default_factory=dict)      # lowercased term -> (facet, value)

    def canonical(self, term):
        return self._lookup.get(term.strip().lower())

    def expand(self, terms):
        """Every term plus its canonical value and that value's whole synonym ring."""
        out = []
        for term in terms:
            for t in [term] + self._ring_of(term):
                if t.lower() not in (o.lower() for o in out):
                    out.append(t)
        return out

    def _ring_of(self, term):
        hit = self.canonical(term)
        if not hit:
            return []
        return [hit[1]] + self.rings.get(hit, [])


def parse_taxonomy(text):
    tax = Taxonomy()
    facet = None
    for line in text.splitlines():
        h = re.match(r"^##\s+(.+?)\s*$", line)
        if h:
            facet = h.group(1).strip().lower()
            tax.facets.setdefault(facet, [])
            continue
        if facet is None or not line.startswith("- "):
            continue
        value, _, syns = line[2:].partition(":")
        value = value.strip()
        if not value:
            continue
        synonyms = [s.strip() for s in syns.split(",") if s.strip()]
        tax.facets[facet].append(value)
        tax.rings[(facet, value)] = synonyms
        for term in [value] + synonyms:
            tax._lookup.setdefault(term.lower(), (facet, value))
    return tax
