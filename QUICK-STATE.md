# Quick State

> Where `kb` stands today, in one read. Update at the end of every working session.

## Done

- `kb` CLI (stdlib-only Python ≥ 3.9): `search`, `get`, `facets`, `stale`, `lint`, `index`, all with `--json`. Built test-first; unit tests under `tests/` pass.
- CI (`.github/workflows/test.yml`): macOS, Linux and Windows × Python 3.9 and 3.x.

## Next

1. **Taxonomy and tags:** draft `TAXONOMY.md` (closed vocabulary plus a synonym ring per value) from the existing KB headings, get it approved, and tag the bases. `kb lint` lists what is missing.
2. **Migrate agent knowledge** into bases that `kb` can query: the `delegation` base (task map, model guide, delegation notes), then the knowledge of the skill-forge plugin.
3. **Readers use `kb`:** skills that read the KB call `kb search` / `kb get` and fall back to `INDEX.md`; preflight calls `kb stale` and `kb lint`.
4. **Convert repo knowledge** (`<repo>/.claude/knowledge`) to the tagged format, one branch per repo.
5. **Install last:** put `kb` on the PATH (a local clone link on the owner's machine, a pinned download elsewhere), wired in by the setup repo's deploy script.

## Notes

- Until step 5, run it from the clone: `~/GitHub/kb/bin/kb` (or `python3 kb`).
- The index is a derived cache (OS cache folder) and is never committed.
