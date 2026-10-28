# Quick State

> Where `kb` stands today, in one read. Update at the end of every working session.

## Done

- `kb` CLI (stdlib-only Python ≥ 3.9): `search`, `get`, `facets`, `stale`, `lint`, `index`, all with `--json`. Built test-first; unit tests under `tests/` pass.
- CI (`.github/workflows/test.yml`): macOS, Linux and Windows × Python 3.9 and 3.x.
- Review fixes (2026-10-28): rule text ranks before tag-only matches; a missing KB folder and an empty query are errors.
- Taxonomy and tags (2026-10-28): global KB tagged against `TAXONOMY.md` (lobomorir-ai-setup PR #10, merged). `kb lint` reports 0 errors on the global KB.

## Next

1. **Migrate agent knowledge** into bases that `kb` can query: the `delegation` base (in progress, lobomorir-ai-setup #15), then the knowledge of the skill-forge plugin. Results measured on one machine never go in the KB: they live in `profiles/<person>/machines/<machine>/benchmark/`.
2. **skill-forge pass over the KB skills and agents** (`kb-pipeline` and its subagents, `update-knowledge-base`, `ask-knowledge-base`, `refresh-forge-kb`, the legacy `kb-*` agents), one task per agent. Also: repo `CLAUDE.md` files down to ≤ 20 lines (profiles are already ≤ 40, lobomorir-ai-setup #17).
3. **Readers use `kb`:** skills that read the KB call `kb search` / `kb get` and fall back to `INDEX.md`; preflight calls `kb stale` and `kb lint`.
4. **Convert repo knowledge** (`<repo>/.claude/knowledge`) to the tagged format, one branch per repo.
5. **Install last:** put `kb` on the PATH (a local clone link on the owner's machine, a pinned download elsewhere), wired in by the setup repo's deploy script.

## Notes

- Until step 5, run it from the clone: `~/GitHub/kb/bin/kb` (or `python3 kb`).
- The index is a derived cache (OS cache folder) and is never committed.
