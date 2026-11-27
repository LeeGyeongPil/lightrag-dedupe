"""AC-2 and AC-3: golden plan, determinism, read-only and LightRAG-free scan."""
import hashlib
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from conftest import ALIASES, ROOT, SAMPLE_GRAPH_DIR

from lightrag_dedupe.aliases import load_aliases
from lightrag_dedupe.candidates import scan_graph
from lightrag_dedupe.cli import main
from lightrag_dedupe.graphml import load_graph
from lightrag_dedupe.plan import plan_csv_text, plan_json_text

GOLDEN = ROOT / "tests" / "golden" / "sample_plan.json"


def _sample_plan():
    return scan_graph(load_graph(SAMPLE_GRAPH_DIR), load_aliases(ALIASES))


def test_sample_plan_matches_golden():
    """The plan for the bundled sample equals the reviewed golden file.

    Regenerate after changing samples or rules: UPDATE_GOLDEN=1 uv run pytest tests/test_scan.py
    and review the diff by hand.
    """
    text = plan_json_text(_sample_plan())
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(text, encoding="utf-8")
    assert text == GOLDEN.read_text(encoding="utf-8")


def test_sample_plan_content():
    plan = _sample_plan()
    by_target = {g.target: g for g in plan.groups}
    openai = by_target["OpenAI"]  # not 오픈AI의, not 'OpenAI Inc.'
    assert sorted(openai.sources) == ["OpenAI Inc.", "openai", "오픈AI의"]
    assert openai.apply is True and openai.flags == []
    apple = next(g for g in plan.groups if {m.name for m in g.members} == {"Apple", "apple"})
    assert apple.flags == ["type_conflict"] and apple.apply is False
    assert [(r.target, r.sources, r.apply, r.flags) for r in plan.review] == [("OpenAI", ["OpenAl"], False, ["near"])]
    assert by_target["삼성전자"].apply and by_target["카카오"].apply
    # traps stay untouched: 마이크로 and Co are in no group
    grouped = {m.name for g in plan.groups for m in g.members}
    assert "마이크로" not in grouped and "Co" not in grouped


def test_scan_is_deterministic(tmp_path):
    runs = []
    for i in (1, 2):
        out, csv_out = tmp_path / f"p{i}.json", tmp_path / f"p{i}.csv"
        assert main(["scan", str(SAMPLE_GRAPH_DIR), "--out", str(out), "--csv", str(csv_out), "--aliases", str(ALIASES), "--lang", "en"]) == 0
        runs.append((out.read_bytes(), csv_out.read_bytes()))
    assert runs[0] == runs[1]
    assert runs[0][0] == plan_json_text(_sample_plan()).encode("utf-8")
    assert runs[0][1] == plan_csv_text(_sample_plan()).encode("utf-8-sig")


def _tree_hashes(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def test_scan_is_read_only_and_lightrag_free(tmp_path):
    before = _tree_hashes(SAMPLE_GRAPH_DIR)
    script = (
        "import sys\n"
        "from lightrag_dedupe.cli import main\n"
        f"rc = main(['scan', 'samples/sample_kg', '--out', {str(tmp_path / 'plan.json')!r}, "
        f"'--csv', {str(tmp_path / 'plan.csv')!r}, '--aliases', 'samples/aliases.csv', '--lang', 'en'])\n"
        "bad = [m for m in sys.modules if m == 'lightrag' or m.startswith('lightrag.')]\n"
        "print('LIGHTRAG_IMPORTED', bad)\n"
        "sys.exit(rc)\n"
    )
    proc = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert "groups:" in proc.stdout and "review:" in proc.stdout
    assert "LIGHTRAG_IMPORTED []" in proc.stdout
    assert (tmp_path / "plan.json").is_file() and (tmp_path / "plan.csv").is_file()
    assert _tree_hashes(SAMPLE_GRAPH_DIR) == before
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dependencies"] == []


def test_max_review_truncates_and_reports(tmp_path):
    plan = scan_graph(load_graph(SAMPLE_GRAPH_DIR), load_aliases(ALIASES), max_review=0)
    assert plan.review == [] and plan.review_truncated == 1


def test_near_threshold_filters_pairs():
    graph = load_graph(SAMPLE_GRAPH_DIR)
    assert len(scan_graph(graph, load_aliases(ALIASES), near=0.7).review) == 0
    assert len(scan_graph(graph, load_aliases(ALIASES), near=0.5).review) >= 1


def test_scan_errors_have_a_fix(tmp_path, capsys):
    assert main(["scan", str(tmp_path / "nope"), "--lang", "en"]) == 2
    err = capsys.readouterr().err
    assert "graph file not found" in err and "working directory" in err
    assert main(["scan", str(SAMPLE_GRAPH_DIR), "--out", str(tmp_path / "x.json"), "--near", "0", "--lang", "en"]) == 2
    bad = tmp_path / "bad.graphml"
    bad.write_text("not xml", encoding="utf-8")
    assert main(["scan", str(bad), "--lang", "en"]) == 2
    assert not (tmp_path / "x.json").exists()
