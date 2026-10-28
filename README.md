# kb

Search Markdown knowledge bases with filters, and get back only what you need.

`kb` indexes a folder of Markdown files into SQLite full-text search (FTS5) and answers
queries with **atomic rules** (one bullet each, ~50 tokens) or **one section**, instead of
whole files. Any AI tool that can run a shell command can use it: Claude Code, opencode,
Codex, local models. Stdlib-only Python ≥ 3.9; nothing to install but the script.

The Markdown files stay the source of truth. The index is derived: it rebuilds itself
whenever a Markdown file, `TAXONOMY.md`, or `kb` itself changes. Rebuilding costs no model
tokens and takes about a second.

## Commands

```bash
kb search "error messages" --base ux --tag a11y --tier proven --fresh
kb search "palette" --project wedding-site      # another repo's knowledge
kb get ux/forms-and-errors#validation           # one section
kb get ux/forms-and-errors                      # outline of a file
kb facets                                       # tag values and counts
kb stale                                        # review_by passed or missing
kb lint                                         # tags vs TAXONOMY.md, missing metadata
kb index                                        # force a rebuild (normally automatic)
```

Every command takes `--json`. Search filters: `--base`, `--tag` (any facet value or synonym),
`--facet facet=value`, `--tier advisory|proven`, `--fresh`, `--raw`, `--limit`.

`--facet` takes any tagged facet from `TAXONOMY.md` or an automatic one: `base`, `tier`,
`fresh` (`fresh`, `expired`, `unknown`), `source` (publisher), `file`. An unknown facet is an
error (exit 2). `kb facets` lists both kinds with counts.

Search tries the exact phrase first, then all words, then any word; each query word also
matches its synonym ring. At each level, rules whose own text or heading has the words rank
before rules that only carry a matching tag. A missing KB folder or an empty query is an error
(exit 2 for `search`, 1 for the other commands), so "no KB" never looks like "no results". Scope: the global KB plus the knowledge of the repo you are in; add
`--project NAME` for another repo, `--all` for every one. `stale`, `facets` and `lint` use the
same scope.

## Knowledge format

```markdown
---
tier: advisory            # advisory = from docs; proven = run on this machine
last_verified: 2026-10-23
review_by: 2026-11-23     # kb stale flags it after this date
sources:
  - publisher: GOV.UK Design System
    url: https://design-system.service.gov.uk/patterns/names/
---

# Forms

## Validation
<!-- tags: topic=forms,validation; platform=web; concern=a11y; keywords=error message, inline error -->
- Show the error next to the field and in a summary at the top. [GOV.UK: https://…]
```

- `##` and `###` headings are sections; a `###` inherits its parent's tags.
- A rule is a `- ` bullet; its source goes in a trailing `[…]`.
- `kind: decisions` in the frontmatter marks a file of the team's own decisions: there, a rule
  that ends with a date (`2026-07`, `2026-10-22`, optionally `2026-10-28 (replaces …)`) counts as
  sourced for `kb lint`. Without the key, a rule needs a `[source]`.
- Sections without bullets are indexed as prose, so unconverted notes stay findable.
- Tags: several values per facet. `keywords` is free text for findability; every other facet
  must use the values in `TAXONOMY.md`.

## TAXONOMY.md

A closed vocabulary with a synonym ring per value. A search or `--tag` with any synonym
reaches the canonical value.

```markdown
## concern
- a11y: accessibility, accesibilidad
```

## Locations

| What | Default | Override |
|---|---|---|
| Global KB | `~/dev/claude-kb` | `KB_ROOT` |
| Repo knowledge | `<repo>/.claude/knowledge`, up to 4 folders deep under `~/GitHub` | `KB_PROJECTS_ROOT` |
| Index | OS cache (`~/Library/Caches/kb`, `$XDG_CACHE_HOME/kb`, `%LOCALAPPDATA%\kb`) | `KB_INDEX` |
| Today's date (for `fresh`/`stale`) | system date | `KB_TODAY` (`YYYY-MM-DD`) |

A project is named after its repo folder; when two repos share a name, both use their path
relative to the projects root.

Skipped at a knowledge root: `INDEX.md`, `TAXONOMY.md`, `README.md`, `templates/`. A
`templates/` folder deeper down is indexed. `.raw/` only with `--raw`.

`kb lint` reports errors (unknown facet, value not in `TAXONOMY.md`) and warnings (no `tier`,
no `review_by`, no tags, prose section, rule without a source). It exits 1 on errors.

## Develop

```bash
python3 -m unittest discover -s tests -t .
```
