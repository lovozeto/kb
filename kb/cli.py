"""Command-line interface: kb search | get | facets | stale | lint | index."""

import argparse
import json
import os
import sys

from kb import index

TEXT_WIDTH = 300


def _scope(args):
    """Global KB + the repo you are in + any --project; --all means every project."""
    if getattr(args, "all", False):
        return index.Scope(everything=True)
    projects = set(getattr(args, "project", None) or [])
    here = index.current_project(os.getcwd(), index.find_project_kbs(index.projects_root()))
    if here:
        projects.add(here)
    return index.Scope(projects=projects)


def _emit(data, as_json, render):
    """Print data as JSON, or as text lines produced by render(data)."""
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
    else:
        for line in render(data):
            print(line)


def _clip(text):
    return text if len(text) <= TEXT_WIDTH else text[:TEXT_WIDTH - 1].rstrip() + "…"


def cmd_search(args):
    con, taxonomy = index.open_index()
    filters = index.Filters(bases=args.base or [], tags=args.tag or [], facets=args.facet or [],
                            tier=args.tier, fresh=args.fresh, raw=args.raw, scope=_scope(args))
    hits = index.search(con, taxonomy, " ".join(args.query), filters, limit=args.limit)
    _emit(hits, args.json, lambda rows: [
        "%s · %s%s" % (h["ref"], _clip(h["text"]), " [%s]" % h["source"] if h["source"] else "")
        for h in rows])
    return 0


def cmd_get(args):
    con, _ = index.open_index()
    if "#" in args.ref:
        text = index.get_section(con, args.ref)
        if text is None:
            raise index.KbError("no section %s (try `kb get %s` for its outline)"
                                % (args.ref, args.ref.split("#")[0]))
        if args.json:
            print(json.dumps({"ref": args.ref, "text": text}, ensure_ascii=False))
        else:
            print(text, end="")
        return 0
    sections = index.outline(con, args.ref)
    if not sections:
        raise index.KbError("no file %s" % args.ref)
    _emit(sections, args.json, lambda rows: [
        "%s#%s · %s (%d rules)" % (args.ref, r["anchor"], r["heading"], r["rules"]) for r in rows])
    return 0


def cmd_facets(args):
    con, _ = index.open_index()
    _emit(index.facet_counts(con, _scope(args)), args.json, lambda counts: [
        "%s: %s" % (facet, ", ".join("%s (%d)" % kv for kv in values.items()))
        for facet, values in counts.items()])
    return 0


def cmd_stale(args):
    con, _ = index.open_index()
    _emit(index.stale_files(con, _scope(args)), args.json, lambda rows: [
        "%s · %s %s" % (r["ref"], r["reason"], r["review_by"] or "") for r in rows])
    return 0


def cmd_lint(args):
    con, taxonomy = index.open_index()
    report = index.lint(con, taxonomy, _scope(args))
    _emit(report, args.json, lambda rep: (
        ["ERROR  " + e for e in rep["errors"]] + ["warn   " + w for w in rep["warnings"]] +
        ["%d error(s), %d warning(s)" % (len(rep["errors"]), len(rep["warnings"]))]))
    return 1 if report["errors"] else 0


def cmd_index(args):
    index.open_index(force=True)
    _emit({"index": index.default_index_path()}, args.json,
          lambda d: ["kb: index rebuilt at %s" % d["index"]])
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="kb", description=__doc__)
    commands = parser.add_subparsers(dest="cmd", required=True)

    def with_scope(cmd):
        cmd.add_argument("--json", action="store_true", help="machine-readable output")
        cmd.add_argument("--project", action="append", metavar="NAME",
                         help="also include this project's knowledge (repeatable)")
        cmd.add_argument("--all", action="store_true", help="include every project")

    search = commands.add_parser("search", help="find rules (atomic facts) by words and filters")
    search.add_argument("query", nargs="+")
    search.add_argument("--base", action="append", help="limit to a base (repeatable)")
    search.add_argument("--tag", action="append", help="any tag value or synonym (repeatable)")
    search.add_argument("--facet", action="append", metavar="FACET=VALUE",
                        help="tagged facet or base|tier|fresh|source|file (repeatable)")
    search.add_argument("--tier", choices=["advisory", "proven"])
    search.add_argument("--fresh", action="store_true", help="only files whose review_by is ahead")
    search.add_argument("--raw", action="store_true", help="include .raw/ source captures")
    search.add_argument("--limit", type=int, default=8)
    with_scope(search)
    search.set_defaults(func=cmd_search)

    get = commands.add_parser("get", help="print one section (file#anchor) or a file's outline")
    get.add_argument("ref")
    with_scope(get)
    get.set_defaults(func=cmd_get)

    facets = commands.add_parser("facets", help="tag and automatic facet values, with counts")
    with_scope(facets)
    facets.set_defaults(func=cmd_facets)

    stale = commands.add_parser("stale", help="files whose review_by has passed or is missing")
    with_scope(stale)
    stale.set_defaults(func=cmd_stale)

    lint = commands.add_parser("lint", help="check tags against TAXONOMY.md and missing metadata")
    with_scope(lint)
    lint.set_defaults(func=cmd_lint)

    rebuild = commands.add_parser("index", help="force a full rebuild (normally automatic)")
    rebuild.add_argument("--json", action="store_true")
    rebuild.set_defaults(func=cmd_index)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except index.KbError as exc:
        print("kb: %s" % exc, file=sys.stderr)
        return 2 if args.cmd == "search" else 1
