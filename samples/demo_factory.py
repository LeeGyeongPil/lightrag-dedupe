"""Example factory for `lightrag-dedupe apply --rag samples/demo_factory.py:build_rag`.

A factory takes no arguments and returns a LightRAG instance that has NOT been initialized yet.
The tool calls initialize_storages() / finalize_storages() itself.

Here the instance is the practice mock (hash embeddings) over the folder named by RAG_WORKING_DIR.
For your own data, build LightRAG exactly like in your indexing script, with YOUR embedding
function, otherwise LightRAG refuses to open the workspace.
"""
import os

from lightrag_dedupe.demo import build_mock_rag


def build_rag():
    return build_mock_rag(os.environ["RAG_WORKING_DIR"])
