"""Regenerate samples/sample_kg/graph_chunk_entity_relation.graphml (offline, no keys).

Usage: uv run python scripts/make_sample.py
Builds a throw-away LightRAG workspace from samples/sample_kg.json with the practice-mock
tokenizer/embedding, then copies only the graphml (all that `scan` reads) into samples/sample_kg/.
"""
import shutil
import tempfile
from pathlib import Path

from lightrag_dedupe.demo import create_sample_working_dir
from lightrag_dedupe.graphml import GRAPHML_NAME

target = Path(__file__).resolve().parent.parent / "samples" / "sample_kg"
with tempfile.TemporaryDirectory() as tmp:
    create_sample_working_dir(tmp)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(tmp) / GRAPHML_NAME, target / GRAPHML_NAME)
print(f"wrote {target / GRAPHML_NAME}")
