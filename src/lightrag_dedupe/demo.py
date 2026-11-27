"""Practice mock: run the whole scan -> apply -> rescan loop on a throw-away LightRAG workspace.

What is real: LightRAG itself (the installed ``lightrag-hku``), its graph storage, its
``amerge_entities`` and its vector-store update.
What is a mock (labelled as such in the output):
  * the tokenizer counts one token per character (the default one downloads a file),
  * embeddings are SHA-256 hash vectors - they carry no meaning, only a stable shape,
  * the LLM function raises if called (merging does not need an LLM; this proves it).
The demo always uses a fresh temporary folder, never a folder you give it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Any

from .aliases import load_aliases
from .apply_python import merge_all, run_sync
from .applylog import ApplyLog
from .candidates import scan_graph
from .errors import UsageError
from .graphml import Graph, load_graph
from .i18n import Translator
from .plan import Merge
from .report import scan_summary

MOCK_MODEL_NAME = "practice-mock-hash"
EMBED_DIM = 32


class CharTokenizer:
    """One token per Unicode code point (offline stand-in for the default tokenizer)."""

    def encode(self, content: str) -> list[int]:
        return [ord(c) for c in content]

    def decode(self, tokens: list[int]) -> str:
        return "".join(chr(t) for t in tokens)


async def _hash_embed(texts: list[str], **_: Any) -> Any:
    """Deterministic fake embeddings: SHA-256 bytes -> 32 floats, normalized."""
    import numpy as np

    rows = []
    for text in texts:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vec = np.frombuffer(digest * 2, dtype=np.uint8)[:EMBED_DIM].astype(np.float32)
        rows.append(vec / (np.linalg.norm(vec) + 1e-9))
    return np.array(rows)


async def _no_llm(prompt: str, **_: Any) -> str:
    raise RuntimeError("the LLM must never be called by this tool")


def build_mock_rag(working_dir: str | Path) -> Any:
    """Return an (uninitialized) LightRAG instance wired with the practice-mock pieces.

    Raises:
        UsageError: the optional ``lightrag`` extra is not installed.
    """
    try:
        from lightrag import LightRAG
        from lightrag.utils import EmbeddingFunc, Tokenizer
    except ImportError as exc:
        raise UsageError("err.extra_missing") from exc
    return LightRAG(
        working_dir=str(working_dir),
        llm_model_func=_no_llm,
        tokenizer=Tokenizer("char", CharTokenizer()),
        embedding_func=EmbeddingFunc(
            embedding_dim=EMBED_DIM, func=_hash_embed, max_token_size=8192, model_name=MOCK_MODEL_NAME
        ),
    )


def sample_dir() -> Path:
    """Folder with ``sample_kg.json`` and ``aliases.csv`` (installed copy first, repo checkout second)."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "samples", here.parent.parent / "samples"):
        if (candidate / "sample_kg.json").is_file():
            return candidate
    raise UsageError("err.sample_missing")


async def populate(working_dir: str | Path, kg: dict[str, Any]) -> None:
    """Insert a hand-written knowledge graph (no LLM involved) with ``ainsert_custom_kg``."""
    rag = build_mock_rag(working_dir)
    await rag.initialize_storages()
    try:
        await rag.ainsert_custom_kg(kg)
    finally:
        await rag.finalize_storages()


def create_sample_working_dir(working_dir: str | Path) -> None:
    """Build a LightRAG working directory from ``samples/sample_kg.json`` (offline)."""
    kg = json.loads((sample_dir() / "sample_kg.json").read_text(encoding="utf-8"))
    Path(working_dir).mkdir(parents=True, exist_ok=True)
    run_sync(populate(working_dir, kg))


def _vdb_entity_names(working_dir: Path) -> set[str]:
    path = working_dir / "vdb_entities.json"
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(d.get("entity_name")) for d in data.get("data", []) if d.get("entity_name")}


def _merged_relations(before: Graph, after: Graph, merges: list[Merge]) -> list[tuple[str, str, int, float]]:
    """For each merged group and neighbor: (target, neighbor, relations before, weight after)."""
    rows: list[tuple[str, str, int, float]] = []
    for m in merges:
        members = {m.target, *m.sources}
        counts: dict[str, int] = {}
        for e in before.edges:
            if e.source in members and e.target not in members:
                counts[e.target] = counts.get(e.target, 0) + 1
            elif e.target in members and e.source not in members:
                counts[e.source] = counts.get(e.source, 0) + 1
        for neighbor, count in sorted(counts.items()):
            if count < 2:
                continue
            for e in after.edges:
                if {e.source, e.target} == {m.target, neighbor} and e.weight is not None:
                    rows.append((m.target, neighbor, count, e.weight))
                    break
    return rows


def run_demo(tr: Translator, out: Callable[[str], None] = print) -> int:
    """Run the practice-mock loop and print what happened. Returns 0 on success."""
    try:
        import lightrag  # noqa: F401
    except ImportError as exc:
        raise UsageError("err.extra_missing") from exc
    # LightRAG logs every storage step (and first-start warnings) through its own handler;
    # silence log records up to WARNING while the demo runs so its output stays readable.
    logging.disable(logging.WARNING)
    try:
        return _run_demo(tr, out)
    finally:
        logging.disable(logging.NOTSET)


def _run_demo(tr: Translator, out: Callable[[str], None]) -> int:
    version = metadata.version("lightrag-hku")
    sample = sample_dir()
    kg = json.loads((sample / "sample_kg.json").read_text(encoding="utf-8"))
    aliases = load_aliases(sample / "aliases.csv")

    out(tr("demo.banner", version=version))
    with tempfile.TemporaryDirectory(prefix="lightrag-dedupe-demo-") as tmp:
        wd = Path(tmp) / "rag_storage"
        wd.mkdir()
        out(tr("demo.step_build"))
        run_sync(populate(wd, kg))
        before = load_graph(wd)
        vdb_before = _vdb_entity_names(wd)

        out(tr("demo.step_scan"))
        plan = scan_graph(before, aliases)
        for line in scan_summary(plan, before, tr):
            out(line)

        merges = [Merge(g.id, g.target, tuple(g.sources)) for g in plan.groups if g.apply]
        out(tr("demo.step_apply", count=len(merges)))
        rag = build_mock_rag(wd)
        run_sync(merge_all(rag, merges, ApplyLog(Path(tmp) / "apply-log.jsonl")))

        after = load_graph(wd)
        vdb_after = _vdb_entity_names(wd)
        merged_away = {s for m in merges for s in m.sources}
        out(tr("demo.step_result"))
        out(tr("demo.nodes", before=len(before.nodes), after=len(after.nodes)))
        out(tr("demo.vdb", before=len(vdb_before), after=len(vdb_after), left=len(merged_away & vdb_after)))
        for target, neighbor, count, weight in _merged_relations(before, after, merges):
            out(tr("demo.relation", target=target, neighbor=neighbor, count=count, weight=f"{weight:.1f}"))
        after_plan = scan_graph(after, aliases)
        auto_left = sum(1 for g in after_plan.groups if g.apply)
        out(tr("demo.rescan", auto=auto_left, groups=len(after_plan.groups), review=len(after_plan.review)))
        out(tr("demo.reminder"))
    return 0
