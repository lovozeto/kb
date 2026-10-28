# Quick State

> Where `kb` stands today, in one read. Update at the end of every working session.

## Done

- `kb` CLI (stdlib-only Python ≥ 3.9): `search`, `get`, `facets`, `stale`, `lint`, `index`, all with `--json`. Built test-first; unit tests under `tests/` pass.
- CI (`.github/workflows/test.yml`): macOS, Linux and Windows × Python 3.9 and 3.x.
- Review fixes (2026-10-28): rule text ranks before tag-only matches; a missing KB folder and an empty query are errors.
- Taxonomy and tags (2026-10-28): global KB tagged against `TAXONOMY.md` (lobomorir-ai-setup PR #10, merged). `kb lint` reports 0 errors on the global KB.
- `delegation` base (2026-10-28, step 3 of the KB plan): `shared/claude-kb/delegation/` in lobomorir-ai-setup, atomic tagged rules with dates (routing, local and cloud models, QA, prompting, machine setup) plus the benchmark baseline. The `delegation` plugin in lovozeto/skills reads it with `kb search --base delegation` / `kb get hardware`, falling back to `$KB_ROOT/INDEX.md`. PRs open, not merged.
- `kind: decisions` (2026-10-28): in a file that declares it in the frontmatter, a rule ending with a date (`YYYY-MM[-DD]`, optional `(text)`) counts as sourced for `kb lint`.

## Next

The KB plan's remaining steps are issues on the board: **https://github.com/users/lovozeto/projects/2** (#8–#12). Previous version: `git show 55c6554:QUICK-STATE.md`.

## Notes

- Until #12 (install on the PATH), run it from the clone: `~/GitHub/kb/bin/kb` (or `python3 kb`).
- The index is a derived cache (OS cache folder) and is never committed.
