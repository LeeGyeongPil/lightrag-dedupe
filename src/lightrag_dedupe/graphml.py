"""Read-only graphml loader for a LightRAG working directory (standard library only).

LightRAG's default NetworkX storage writes ``graph_chunk_entity_relation.graphml`` where the node
id is the entity name. Attribute keys are looked up by ``attr.name`` because the numeric key ids
differ between versions. Multi-valued fields are joined with ``<SEP>``.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .errors import UsageError

GRAPHML_NAME = "graph_chunk_entity_relation.graphml"
_NS = "{http://graphml.graphdrawing.org/xmlns}"
SEP = "<SEP>"


@dataclass(frozen=True)
class Node:
    """A graph node as stored: ``name`` is the exact node id (what merge APIs need)."""

    name: str
    entity_type: str
    degree: int
    chunks: int  # number of source chunks mentioning the entity (``source_id`` parts)


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    weight: float | None


@dataclass
class Graph:
    path: Path
    sha256: str
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)


def resolve_graph_path(path: str | Path, workspace: str | None = None) -> Path:
    """Find the graphml file for a working directory, a workspace sub-folder or a file path.

    Raises:
        UsageError: when no graphml file can be found.
    """
    p = Path(path)
    if p.is_file():
        return p
    base = p / workspace if workspace else p
    candidate = base / GRAPHML_NAME
    if candidate.is_file():
        return candidate
    raise UsageError("err.graph_missing", path=str(candidate))


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_graph(path: str | Path, workspace: str | None = None) -> Graph:
    """Parse the graphml file. Never writes anything.

    Raises:
        UsageError: file missing or not valid graphml.
    """
    gpath = resolve_graph_path(path, workspace)
    try:
        root = ET.parse(gpath).getroot()
    except (ET.ParseError, OSError) as exc:
        raise UsageError("err.graph_invalid", path=str(gpath), detail=str(exc)) from exc

    keys = {k.get("id"): k.get("attr.name") for k in root.iter(_NS + "key")}
    raw: dict[str, tuple[str, int]] = {}
    for node in root.iter(_NS + "node"):
        attrs = {keys.get(d.get("key"), d.get("key")): (d.text or "") for d in node.findall(_NS + "data")}
        source_id = attrs.get("source_id", "")
        chunks = len([part for part in source_id.split(SEP) if part])
        raw[node.get("id", "")] = (attrs.get("entity_type", "").strip(), chunks)

    degree = dict.fromkeys(raw, 0)
    edges: list[Edge] = []
    for edge in root.iter(_NS + "edge"):
        src, tgt = edge.get("source", ""), edge.get("target", "")
        degree[src] = degree.get(src, 0) + 1
        degree[tgt] = degree.get(tgt, 0) + 1
        attrs = {keys.get(d.get("key"), d.get("key")): (d.text or "") for d in edge.findall(_NS + "data")}
        try:
            weight: float | None = float(attrs["weight"])
        except (KeyError, ValueError):
            weight = None
        edges.append(Edge(src, tgt, weight))

    graph = Graph(path=gpath, sha256=file_sha256(gpath), edges=edges)
    for name, (etype, chunks) in raw.items():
        graph.nodes[name] = Node(name=name, entity_type=etype, degree=degree.get(name, 0), chunks=chunks)
    return graph
