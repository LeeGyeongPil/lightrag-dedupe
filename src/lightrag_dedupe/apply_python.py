"""Merge through the Python API: the user's own factory returns their LightRAG instance.

The factory is what makes this safe: LightRAG re-embeds merged entities, so the instance must be
built with the *real* embedding function of the workspace (a different model is refused at start).
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .applylog import ApplyLog
from .errors import ApplyError, UsageError
from .plan import Merge


def load_factory(spec: str) -> Callable[[], Any]:
    """Resolve ``path/to/file.py:func`` or ``package.module:func`` to a callable.

    Raises:
        UsageError: bad spec, file or module not importable, attribute missing or not callable.
    """
    module_part, sep, func_name = spec.rpartition(":")
    if not sep or not module_part or not func_name:
        raise UsageError("err.factory_spec", spec=spec)
    try:
        if module_part.endswith(".py") or "/" in module_part:
            path = Path(module_part).resolve()
            if not path.is_file():
                raise UsageError("err.factory_file", path=str(path))
            sys.path.insert(0, str(path.parent))
            mod_spec = importlib.util.spec_from_file_location(f"_lightrag_dedupe_factory_{path.stem}", path)
            if mod_spec is None or mod_spec.loader is None:
                raise UsageError("err.factory_file", path=str(path))
            module = importlib.util.module_from_spec(mod_spec)
            mod_spec.loader.exec_module(module)
        else:
            sys.path.insert(0, str(Path.cwd()))
            module = importlib.import_module(module_part)
    except ImportError as exc:
        missing = getattr(exc, "name", None) or ""
        if isinstance(exc, ModuleNotFoundError) and missing and missing.split(".")[0] != "lightrag":
            raise UsageError("err.factory_import_user", spec=spec, detail=str(exc), module=missing) from exc
        raise UsageError("err.factory_import", spec=spec, detail=str(exc)) from exc
    func = getattr(module, func_name, None)
    if not callable(func):
        raise UsageError("err.factory_attr", spec=spec, name=func_name)
    return func  # type: ignore[no-any-return]


async def build_rag(factory: Callable[[], Any] | Callable[[], Awaitable[Any]]) -> Any:
    """Call the factory (sync or async) and check that it returned something mergeable."""
    rag = factory()
    if inspect.isawaitable(rag):
        rag = await rag
    if not hasattr(rag, "amerge_entities") or not hasattr(rag, "initialize_storages"):
        raise UsageError("err.factory_result", type=type(rag).__name__)
    return rag


async def merge_all(
    rag: Any,
    merges: list[Merge],
    log: ApplyLog,
    progress: Callable[[int, int, Merge], None] | None = None,
) -> None:
    """Initialize storages, call ``amerge_entities`` per group, always finalize.

    Raises:
        ApplyError: a merge raised; groups finished before it stay in the log.
    """
    await rag.initialize_storages()
    try:
        for n, merge in enumerate(merges, start=1):
            if progress:
                progress(n, len(merges), merge)
            try:
                await rag.amerge_entities(source_entities=list(merge.sources), target_entity=merge.target)
            except Exception as exc:  # LightRAG raises ValueError, RuntimeError, ...
                log.record(merge, "failed", f"{type(exc).__name__}: {exc}")
                raise ApplyError("err.apply_failed", id=merge.id, detail=f"{type(exc).__name__}: {exc}") from exc
            log.record(merge, "done")
    finally:
        await rag.finalize_storages()


def run_sync(coro: Awaitable[Any]) -> Any:
    """Run a coroutine from the synchronous CLI."""
    return asyncio.run(coro)  # type: ignore[arg-type]
