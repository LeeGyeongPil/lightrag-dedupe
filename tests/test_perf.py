"""AC-10: a 20,000-node graph is scanned within 15 CPU-seconds (about 1 s measured; CPU time so machine load cannot flake it)."""
import random
import time
from xml.sax.saxutils import escape

from lightrag_dedupe.candidates import scan_graph
from lightrag_dedupe.graphml import load_graph


def _write_graph(path, names):
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '<key id="d0" for="node" attr.name="entity_type" attr.type="string"/>',
        '<key id="d1" for="node" attr.name="source_id" attr.type="string"/>',
        '<graph edgedefault="undirected">',
    ]
    for i, name in enumerate(names):
        parts.append(
            f'<node id="{escape(name)}"><data key="d0">{"ORGANIZATION" if i % 3 else "PERSON"}</data>'
            f'<data key="d1">chunk-{i}&lt;SEP&gt;chunk-{i + 1}</data></node>'
        )
    parts.append("</graph></graphml>")
    path.write_text("\n".join(parts), encoding="utf-8")


def test_scan_20k_nodes_under_15s(tmp_path):
    rng = random.Random(7)
    vocab = ["".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(4, 9))) for _ in range(900)]
    names: set[str] = set()
    while len(names) < 19_500:
        names.add(" ".join(rng.choice(vocab) for _ in range(rng.randint(1, 3))).title())
    base = sorted(names)
    # inject known duplicates: suffix and case variants of 500 names
    extra = [f"{n} Inc." for n in base[:250]] + [n.upper() for n in base[250:500]]
    all_names = base + [e for e in extra if e not in names]
    all_names = all_names[:20_000]
    assert len(all_names) == 20_000
    path = tmp_path / "graph_chunk_entity_relation.graphml"
    _write_graph(path, all_names)

    start = time.process_time()
    graph = load_graph(path)
    plan = scan_graph(graph)
    elapsed = time.process_time() - start

    assert len(graph.nodes) == 20_000
    assert len(plan.groups) >= 500
    assert elapsed < 15, f"scan took {elapsed:.1f}s"
