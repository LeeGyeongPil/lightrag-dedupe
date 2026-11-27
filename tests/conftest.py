"""Shared fixtures. Everything runs offline: no keys, no network, no LLM."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
SAMPLE_GRAPH_DIR = SAMPLES / "sample_kg"
ALIASES = SAMPLES / "aliases.csv"
FACTORY = SAMPLES / "demo_factory.py"

_ENV_NAMES = ("LIGHTRAG_DEDUPE_LANG", "LC_ALL", "LC_MESSAGES", "LANG", "LIGHTRAG_API_KEY", "RAG_WORKING_DIR")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Language and key variables of the developer's shell must not leak into tests."""
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session")
def lightrag_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real LightRAG 1.5.8 working directory built once from the sample KG (practice mock)."""
    from lightrag_dedupe.demo import create_sample_working_dir

    path = tmp_path_factory.mktemp("lightrag_template") / "rag_storage"
    create_sample_working_dir(path)
    return path


@pytest.fixture
def rag_dir(lightrag_template: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh copy of the LightRAG working directory; RAG_WORKING_DIR points the factory at it."""
    target = tmp_path / "rag_storage"
    shutil.copytree(lightrag_template, target)
    monkeypatch.setenv("RAG_WORKING_DIR", str(target))
    return target


@pytest.fixture
def sample_plan(tmp_path: Path) -> Path:
    """plan.json scanned from the bundled sample graph."""
    from lightrag_dedupe.aliases import load_aliases
    from lightrag_dedupe.candidates import scan_graph
    from lightrag_dedupe.graphml import load_graph
    from lightrag_dedupe.plan import write_plan_json

    plan = scan_graph(load_graph(SAMPLE_GRAPH_DIR), load_aliases(ALIASES))
    path = tmp_path / "plan.json"
    write_plan_json(plan, path)
    return path
