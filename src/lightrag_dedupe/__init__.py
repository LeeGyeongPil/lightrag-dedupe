"""lightrag-dedupe: deterministic, reviewable duplicate-entity merge plans for LightRAG graphs.

Unofficial tool. Public API:

* :func:`scan_graph` - read a LightRAG working directory (read-only) and build a merge plan.
* :func:`normalize_name` - the rule chain that turns an entity name into a comparison key.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .candidates import scan_graph
from .normalize import NormResult, normalize_name

__all__ = ["NormResult", "__version__", "normalize_name", "scan_graph"]
