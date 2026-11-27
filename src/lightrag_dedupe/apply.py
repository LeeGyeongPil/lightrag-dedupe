"""The ``apply`` workflow: load plan -> preflight -> (dry-run | backup + merge).

Order of safety checks, all before the first merge:
1. the plan file is valid (see :func:`lightrag_dedupe.plan.load_plan`),
2. every source name exists in the current graph, exactly as written (exit code 3 otherwise),
3. a backup of the working directory exists (or ``--no-backup`` was given explicitly for servers).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import apply_python
from .apply_http import LightRagClient
from .applylog import ApplyLog, merge_key
from .backup import create_backup
from .errors import StalePlanError, UsageError
from .graphml import load_graph, resolve_graph_path
from .i18n import Translator
from .plan import LoadedPlan, Merge, load_plan


@dataclass
class ApplyOptions:
    plan_path: str
    working_dir: str | None = None
    workspace: str | None = None
    rag_spec: str | None = None
    server: str | None = None
    yes: bool = False
    limit: int | None = None
    backup_dir: str | None = None
    no_backup: bool = False
    log_path: str | None = None
    api_key: str | None = None


def _read_nodes(working_dir: str | None, workspace: str | None) -> tuple[set[str], str] | None:
    """Names and sha256 of the current graph, or ``None`` when no working dir is known."""
    if not working_dir:
        return None
    graph = load_graph(working_dir, workspace)
    return set(graph.nodes), graph.sha256


def _pending(loaded: LoadedPlan, log: ApplyLog, nodes: set[str] | None) -> list[Merge]:
    """Groups still to do. A logged group counts as done only if its sources are really gone
    (after a restore the sources are back, so the group runs again)."""
    done = log.done_keys()
    pending = []
    for m in loaded.merges:
        if merge_key(m) in done and (nodes is None or not any(s in nodes for s in m.sources)):
            continue
        pending.append(m)
    return pending


def _preflight_graph(pending: list[Merge], nodes: set[str]) -> None:
    missing = [(m.id, s) for m in pending for s in m.sources if s not in nodes]
    if missing:
        first_id, first_name = missing[0]
        raise StalePlanError("err.stale_source", id=first_id, name=first_name, count=len(missing))


def _preflight_server(pending: list[Merge], client: LightRagClient) -> None:
    for m in pending:
        for s in m.sources:
            if not client.entity_exists(s):
                raise StalePlanError("err.stale_source", id=m.id, name=s, count=1)


def run_apply(opts: ApplyOptions, tr: Translator, out: Callable[[str], None] = print) -> int:
    """Run the workflow and return an exit code (0). Errors are raised as ``DedupeError``."""
    if opts.rag_spec and opts.server:
        raise UsageError("err.apply_both_backends")
    if opts.yes and not (opts.rag_spec or opts.server):
        raise UsageError("err.apply_no_backend")
    if opts.limit is not None and opts.limit < 1:
        raise UsageError("err.limit_value")
    if opts.yes and opts.server and not (opts.working_dir or opts.no_backup):
        raise UsageError("err.server_backup_required")

    loaded = load_plan(opts.plan_path)
    log_path = Path(opts.log_path) if opts.log_path else Path(opts.plan_path).resolve().parent / "apply-log.jsonl"
    log = ApplyLog(log_path)
    client = LightRagClient(opts.server, opts.api_key) if opts.server else None

    current = _read_nodes(opts.working_dir, opts.workspace)
    nodes = current[0] if current else None
    if current and loaded.graph_sha256 and loaded.graph_sha256 != current[1]:
        out(tr("apply.warn_sha_changed"))
    pending = _pending(loaded, log, nodes)
    if opts.limit is not None:
        pending = pending[: opts.limit]
    skipped_done = len(loaded.merges) - len(pending) if opts.limit is None else 0

    out(tr("apply.header", total=len(loaded.merges), skipped=loaded.skipped, done=skipped_done))
    if not pending:
        out(tr("apply.nothing"))
        return 0

    if nodes is not None:
        _preflight_graph(pending, nodes)
    elif client is not None:
        _preflight_server(pending, client)

    if not opts.yes:
        _print_dry_run(pending, opts, tr, out, preflight_done=nodes is not None or client is not None)
        return 0

    if client is not None:
        return _apply_server(pending, opts, client, log, tr, out)
    return _apply_rag(pending, opts, log, tr, out)


def _print_dry_run(
    pending: list[Merge], opts: ApplyOptions, tr: Translator, out: Callable[[str], None], preflight_done: bool
) -> None:
    out(tr("apply.dry_run"))
    for n, m in enumerate(pending, start=1):
        names = ", ".join(repr(s) for s in m.sources)
        if opts.server:
            out(tr("apply.call_server", n=n, total=len(pending), id=m.id, sources=names, target=m.target))
        else:
            out(tr("apply.call_python", n=n, total=len(pending), id=m.id, sources=names, target=m.target))
    out(tr("apply.preflight_ok") if preflight_done else tr("apply.preflight_skipped"))
    out(tr("apply.rerun_hint"))


def _backup(opts: ApplyOptions, working_dir: str | None, tr: Translator, out: Callable[[str], None]) -> None:
    if opts.no_backup:
        out(tr("apply.no_backup"))
        return
    if not working_dir:
        raise UsageError("err.backup_no_working_dir")
    path = create_backup(working_dir, opts.backup_dir)
    out(tr("apply.backup_created", path=str(path)))


def _apply_server(
    pending: list[Merge], opts: ApplyOptions, client: LightRagClient, log: ApplyLog, tr: Translator, out: Callable[[str], None]
) -> int:
    _backup(opts, opts.working_dir, tr, out)
    for n, m in enumerate(pending, start=1):
        out(tr("apply.progress", n=n, total=len(pending), id=m.id, target=m.target, count=len(m.sources)))
        try:
            client.merge(list(m.sources), m.target)
        except Exception as exc:
            log.record(m, "failed", str(exc))
            raise
        log.record(m, "done")
    out(tr("apply.finished", count=len(pending)))
    return 0


def _apply_rag(pending: list[Merge], opts: ApplyOptions, log: ApplyLog, tr: Translator, out: Callable[[str], None]) -> int:
    assert opts.rag_spec
    factory = apply_python.load_factory(opts.rag_spec)

    async def go() -> None:
        rag = await apply_python.build_rag(factory)
        working_dir = opts.working_dir or str(getattr(rag, "working_dir", "") or "")
        workspace = opts.workspace or (getattr(rag, "workspace", "") or None)
        if not opts.working_dir:
            # The factory told us where the data lives: preflight against it now.
            graph_file = resolve_graph_path(working_dir, workspace)
            _preflight_graph(pending, set(load_graph(graph_file).nodes))
        _backup(opts, working_dir, tr, out)
        merge_all_progress: Any = lambda n, total, m: out(  # noqa: E731
            tr("apply.progress", n=n, total=total, id=m.id, target=m.target, count=len(m.sources))
        )
        await apply_python.merge_all(rag, pending, log, merge_all_progress)

    apply_python.run_sync(go())
    out(tr("apply.finished", count=len(pending)))
    return 0

