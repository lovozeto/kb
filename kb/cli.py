"""Command-line interface: kb search | get | facets | stale | lint | index."""

import argparse
import json
import os
import sys

from kb import index as ix


def _scope(args, con):
    if getattr(args, "all", False):
        return "all"
    names = set()
    if getattr(args, "project", None):
        names.update(args.project)
    here = ix.current_project(os.getcwd(), ix.find_project_kbs(ix.projects_root()))
    if here:
        names.add(here)
    return names


def _print(rows, as_json, fmt):
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        for r in rows:
            print(fmt(r))


def cmd_search(args):
    con, tax = ix.open_index()
    hits = ix.search(con, tax, " ".join(args.query), bases=args.base or (), tags=args.tag or (),
                     facets=args.facet or (), tier=args.tier, fresh=args.fresh, raw=args.raw,
                     projects=_scope(args, con), limit=args.limit)

    def line(h):
        src = (" [%s]" % h["source"]) if h["source"] else ""
        return "%s · %s%s" % (h["ref"], h["text"][:300], src)
    _print(hits, args.json, line)
    return 0


def cmd_get(args):
    con, _ = ix.open_index()
    if "#" in args.ref:
        text = ix.get_section(con, args.ref)
        if text is None:
            print("kb: no section %s (try `kb get %s` for its outline)"
                  % (args.ref, args.ref.split("#")[0]), file=sys.stderr)
            return 1
        print(json.dumps({"ref": args.ref, "text": text}, ensure_ascii=False) if args.json
              else text, end="" if not args.json else "\n")
        return 0
    rows = ix.outline(con, args.ref)
    if not rows:
        print("kb: no file %s" % args.ref, file=sys.stderr)
        return 1
    _print(rows, args.json,
           lambda r: "%s#%s · %s (%d rules)" % (args.ref, r["anchor"], r["heading"], r["rules"]))
    return 0


def cmd_facets(args):
    con, _ = ix.open_index()
    counts = ix.facet_counts(con, _scope(args, con))
    if args.json:
        print(json.dumps(counts, ensure_ascii=False, indent=1))
    else:
        for facet, values in counts.items():
            print("%s: %s" % (facet, ", ".join("%s (%d)" % kv for kv in values.items())))
    return 0


def cmd_stale(args):
    con, _ = ix.open_index()
    rows = ix.stale_files(con, _scope(args, con))
    _print(rows, args.json, lambda r: "%s · %s %s" % (r["ref"], r["reason"], r["review_by"] or ""))
    return 0


def cmd_lint(args):
    con, tax = ix.open_index()
    report = ix.lint(con, tax)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for e in report["errors"]:
            print("ERROR  " + e)
        for w in report["warnings"]:
            print("warn   " + w)
        print("%d error(s), %d warning(s)" % (len(report["errors"]), len(report["warnings"])))
    return 1 if report["errors"] else 0


def cmd_index(args):
    ix.open_index(force=True)
    print("kb: index rebuilt at %s" % ix.default_index_path())
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="kb", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--json", action="store_true", help="machine-readable output")
        sp.add_argument("--project", action="append", metavar="NAME",
                        help="also include this project's knowledge (repeatable)")
        sp.add_argument("--all", action="store_true", help="include every project")

    s = sub.add_parser("search", help="find rules (atomic facts) matching words and filters")
    s.add_argument("query", nargs="+")
    s.add_argument("--base", action="append", help="limit to a base (repeatable)")
    s.add_argument("--tag", action="append", help="any facet value or synonym (repeatable)")
    s.add_argument("--facet", action="append", metavar="FACET=VALUE")
    s.add_argument("--tier", choices=["advisory", "proven"])
    s.add_argument("--fresh", action="store_true", help="only files whose review_by is ahead")
    s.add_argument("--raw", action="store_true", help="include .raw/ source captures")
    s.add_argument("--limit", type=int, default=8)
    common(s)
    s.set_defaults(func=cmd_search)

    g = sub.add_parser("get", help="print one section (file#anchor) or a file's outline")
    g.add_argument("ref")
    common(g)
    g.set_defaults(func=cmd_get)

    f = sub.add_parser("facets", help="list tag values and how many sections carry each")
    common(f)
    f.set_defaults(func=cmd_facets)

    st = sub.add_parser("stale", help="files whose review_by has passed or is missing")
    common(st)
    st.set_defaults(func=cmd_stale)

    li = sub.add_parser("lint", help="check tags against TAXONOMY.md and missing metadata")
    common(li)
    li.set_defaults(func=cmd_lint)

    i = sub.add_parser("index", help="force a full rebuild (normally automatic)")
    i.add_argument("--json", action="store_true")
    i.set_defaults(func=cmd_index)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)
