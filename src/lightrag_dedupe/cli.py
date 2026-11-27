"""Command line interface: ``lightrag-dedupe scan | explain | apply | restore | demo``.

Exit codes: 0 ok, 2 input/usage error, 3 plan does not match the graph, 4 a merge failed.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Sequence
from typing import NoReturn

from . import __version__
from .aliases import load_aliases
from .apply import ApplyOptions, run_apply
from .apply_http import API_KEY_ENV
from .backup import read_manifest, restore_backup
from .candidates import DEFAULT_MAX_REVIEW, DEFAULT_NEAR, compute_norms, scan_graph
from .errors import EXIT_OK, EXIT_USAGE, DedupeError, UsageError
from .graphml import load_graph
from .i18n import ENV_VAR, SUPPORTED, Translator, resolve_lang
from .plan import write_plan_csv, write_plan_json
from .report import explain_lines, scan_summary


def _preparse_lang(argv: Sequence[str]) -> str | None:
    """Find ``--lang`` anywhere in argv before the real parser is built (help text needs it)."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang")
    known, _ = pre.parse_known_args(list(argv))
    return known.lang if known.lang in SUPPORTED else None


class _Parser(argparse.ArgumentParser):
    """ArgumentParser whose error output is prefixed in the chosen language."""

    tr: Translator

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.tr('error.prefix')}: {_translate_argparse(self.tr, message)}\n")


def _translate_argparse(tr: Translator, message: str) -> str:
    """Translate argparse's own error reasons; unknown patterns stay as argparse wrote them."""
    if m := re.fullmatch(r"the following arguments are required: (.+)", message):
        return tr("argerr.required", names=m.group(1))
    if m := re.fullmatch(r"argument (.+?): invalid choice: (.+?) \(choose from (.+)\)", message):
        return tr("argerr.choice", arg=m.group(1), value=m.group(2), choices=m.group(3))
    if m := re.fullmatch(r"unrecognized arguments: (.+)", message):
        return tr("argerr.unrecognized", names=m.group(1))
    if m := re.fullmatch(r"argument (.+?): invalid (int|float) value: (.+)", message):
        kind = tr("argerr.kind_int") if m.group(2) == "int" else tr("argerr.kind_float")
        return tr("argerr.value", arg=m.group(1), kind=kind, value=m.group(3))
    if m := re.fullmatch(r"argument (.+?): expected one argument", message):
        return tr("argerr.one_argument", arg=m.group(1))
    return message


def _formatter(tr: Translator) -> type[argparse.HelpFormatter]:
    class Formatter(argparse.RawDescriptionHelpFormatter):
        def add_usage(self, usage, actions, groups, prefix=None):  # type: ignore[no-untyped-def]
            # argparse passes prefix='' when it builds a sub-parser's prog; keep that as is.
            return super().add_usage(usage, actions, groups, tr("help.usage") + ": " if prefix is None else prefix)

    return Formatter


def _make_parser(tr: Translator) -> _Parser:
    fmt = _formatter(tr)

    class Parser(_Parser):
        pass

    Parser.tr = tr
    lang_help = tr("help.lang", env=ENV_VAR)
    parser = Parser(
        prog="lightrag-dedupe",
        formatter_class=fmt,
        add_help=False,
        description=tr("help.description"),
        epilog=tr("help.epilog"),
    )
    _prep(parser, tr)
    parser.add_argument("--version", action="version", version=f"lightrag-dedupe {__version__}", help=tr("help.version"))
    parser.add_argument("--lang", choices=SUPPORTED, help=lang_help)
    sub = parser.add_subparsers(dest="command", required=True, metavar="{scan,explain,apply,restore,demo}", title=tr("help.commands"))

    scan = sub.add_parser("scan", help=tr("help.scan"), description=tr("help.scan"), add_help=False, formatter_class=fmt)
    _prep(scan, tr)
    scan.add_argument("path", help=tr("help.scan_path"))
    scan.add_argument("--out", default="plan.json", help=tr("help.scan_out"))
    scan.add_argument("--csv", help=tr("help.scan_csv"))
    scan.add_argument("--aliases", help=tr("help.aliases"))
    scan.add_argument("--workspace", help=tr("help.workspace"))
    scan.add_argument("--near", type=float, default=DEFAULT_NEAR, help=tr("help.near", default=DEFAULT_NEAR))
    scan.add_argument("--max-review", type=int, default=DEFAULT_MAX_REVIEW, help=tr("help.max_review", default=DEFAULT_MAX_REVIEW))
    scan.add_argument("--lang", choices=SUPPORTED, default=argparse.SUPPRESS, help=lang_help)

    explain = sub.add_parser("explain", help=tr("help.explain"), description=tr("help.explain"), add_help=False, formatter_class=fmt)
    _prep(explain, tr)
    explain.add_argument("name", help=tr("help.explain_name"))
    explain.add_argument("--in", dest="source", required=True, help=tr("help.explain_in"))
    explain.add_argument("--aliases", help=tr("help.aliases"))
    explain.add_argument("--workspace", help=tr("help.workspace"))
    explain.add_argument("--lang", choices=SUPPORTED, default=argparse.SUPPRESS, help=lang_help)

    apply_p = sub.add_parser("apply", help=tr("help.apply"), description=tr("help.apply_long"), add_help=False, formatter_class=fmt)
    _prep(apply_p, tr)
    apply_p.add_argument("plan", help=tr("help.apply_plan"))
    apply_p.add_argument("--rag", metavar="FILE.py:FUNC", help=tr("help.apply_rag"))
    apply_p.add_argument("--server", metavar="URL", help=tr("help.apply_server", env=API_KEY_ENV))
    apply_p.add_argument("--working-dir", help=tr("help.apply_working_dir"))
    apply_p.add_argument("--workspace", help=tr("help.workspace"))
    apply_p.add_argument("--yes", action="store_true", help=tr("help.apply_yes"))
    apply_p.add_argument("--limit", type=int, help=tr("help.apply_limit"))
    apply_p.add_argument("--backup-dir", help=tr("help.apply_backup_dir"))
    apply_p.add_argument("--no-backup", action="store_true", help=tr("help.apply_no_backup"))
    apply_p.add_argument("--log", help=tr("help.apply_log"))
    apply_p.add_argument("--lang", choices=SUPPORTED, default=argparse.SUPPRESS, help=lang_help)

    restore = sub.add_parser("restore", help=tr("help.restore"), description=tr("help.restore"), add_help=False, formatter_class=fmt)
    _prep(restore, tr)
    restore.add_argument("backup_dir", help=tr("help.restore_dir"))
    restore.add_argument("--working-dir", help=tr("help.restore_working_dir"))
    restore.add_argument("--yes", action="store_true", help=tr("help.restore_yes"))
    restore.add_argument("--prune", action="store_true", help=tr("help.restore_prune"))
    restore.add_argument("--lang", choices=SUPPORTED, default=argparse.SUPPRESS, help=lang_help)

    demo = sub.add_parser("demo", help=tr("help.demo"), description=tr("help.demo"), add_help=False, formatter_class=fmt)
    _prep(demo, tr)
    demo.add_argument("--lang", choices=SUPPORTED, default=argparse.SUPPRESS, help=lang_help)
    return parser


def _prep(p: argparse.ArgumentParser, tr: Translator) -> None:
    """Localize the built-in -h option and section titles of a sub-parser."""
    p.add_argument("-h", "--help", action="help", help=tr("help.help"))
    p._positionals.title = tr("help.positionals")
    p._optionals.title = tr("help.options")


def _cmd_scan(args: argparse.Namespace, tr: Translator) -> int:
    if not 0 < args.near <= 1:
        raise UsageError("err.near_range", value=args.near)
    if args.max_review < 0:
        raise UsageError("err.max_review_range", value=args.max_review)
    graph = load_graph(args.path, args.workspace)
    aliases = load_aliases(args.aliases)
    plan = scan_graph(graph, aliases, near=args.near, max_review=args.max_review)
    write_plan_json(plan, args.out)
    if args.csv:
        write_plan_csv(plan, args.csv)
    print(tr("scan.title", path=str(graph.path)))
    for line in scan_summary(plan, graph, tr):
        print(line)
    print(tr("scan.wrote", path=args.out))
    if args.csv:
        print(tr("scan.wrote", path=args.csv))
    print(tr("scan.next", plan=args.csv or args.out))
    return EXIT_OK


def _cmd_explain(args: argparse.Namespace, tr: Translator) -> int:
    graph = load_graph(args.source, args.workspace)
    aliases = load_aliases(args.aliases)
    if args.name not in graph.nodes:
        raise UsageError("err.explain_missing", name=args.name)
    norms = compute_norms(sorted(graph.nodes), aliases)
    norm = norms[args.name]
    same = sorted(n for n, r in norms.items() if r.key == norm.key and n != args.name)
    for line in explain_lines(args.name, graph.nodes[args.name].entity_type, norm, same, tr):
        print(line)
    return EXIT_OK


def _cmd_apply(args: argparse.Namespace, tr: Translator) -> int:
    opts = ApplyOptions(
        plan_path=args.plan,
        working_dir=args.working_dir,
        workspace=args.workspace,
        rag_spec=args.rag,
        server=args.server,
        yes=args.yes,
        limit=args.limit,
        backup_dir=args.backup_dir,
        no_backup=args.no_backup,
        log_path=args.log,
        api_key=os.environ.get(API_KEY_ENV),
    )
    return run_apply(opts, tr)


def _cmd_restore(args: argparse.Namespace, tr: Translator) -> int:
    manifest = read_manifest(args.backup_dir)
    target = args.working_dir or manifest.get("source", "")
    if not args.yes:
        print(tr("restore.dry_run", files=len(manifest["files"]), target=target, backup=args.backup_dir))
        print(tr("restore.stop_first"))
        print(tr("restore.rerun_hint"))
        return EXIT_OK
    result = restore_backup(args.backup_dir, args.working_dir, prune=args.prune)
    print(tr("restore.done", files=result.restored, target=str(result.working_dir)))
    if result.extra:
        key = "restore.pruned" if result.pruned else "restore.extra"
        print(tr(key, count=len(result.extra)))
    return EXIT_OK


def _cmd_demo(args: argparse.Namespace, tr: Translator) -> int:
    from .demo import run_demo

    return run_demo(tr)


_COMMANDS = {"scan": _cmd_scan, "explain": _cmd_explain, "apply": _cmd_apply, "restore": _cmd_restore, "demo": _cmd_demo}


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    args_list = list(sys.argv[1:] if argv is None else argv)
    lang = resolve_lang(_preparse_lang(args_list), os.environ)
    tr = Translator(lang)
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(errors="replace")
    parser = _make_parser(tr)
    try:
        args = parser.parse_args(args_list)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_OK
    try:
        return _COMMANDS[args.command](args, tr)
    except DedupeError as exc:
        print(f"{tr('error.prefix')}: {tr(exc.key, **exc.params)}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print(tr("error.interrupted"), file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

