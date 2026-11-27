"""AC-5 and AC-6: real LightRAG 1.5.8 merges, offline (practice-mock tokenizer and embeddings)."""
import hashlib
import json
from pathlib import Path

from conftest import ALIASES, FACTORY

from lightrag_dedupe.aliases import load_aliases
from lightrag_dedupe.candidates import scan_graph
from lightrag_dedupe.cli import main
from lightrag_dedupe.graphml import GRAPHML_NAME, load_graph
from lightrag_dedupe.plan import write_plan_json

SOURCES = {"OpenAI Inc.", "openai", "오픈AI의", "삼성전자의", "Samsung Electronics Co., Ltd.", "(주)카카오", "주식회사 카카오"}
FACTORY_SPEC = f"{FACTORY}:build_rag"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _vdb_names(rag_dir: Path) -> set[str]:
    data = json.loads((rag_dir / "vdb_entities.json").read_text(encoding="utf-8"))
    return {d["entity_name"] for d in data["data"]}


def _plan(rag_dir: Path, tmp_path: Path) -> Path:
    plan = scan_graph(load_graph(rag_dir), load_aliases(ALIASES))
    path = tmp_path / "plan.json"
    write_plan_json(plan, path)
    return path


def _args(plan: Path, rag_dir: Path, tmp_path: Path, *extra: str) -> list[str]:
    return ["apply", str(plan), "--rag", FACTORY_SPEC, "--backup-dir", str(tmp_path / "backups"), "--lang", "en", *extra]


def test_dry_run_changes_nothing(rag_dir, tmp_path, capsys):
    plan = _plan(rag_dir, tmp_path)
    before = _sha(rag_dir / GRAPHML_NAME)
    assert main(["apply", str(plan), "--working-dir", str(rag_dir), "--rag", FACTORY_SPEC, "--lang", "en"]) == 0
    out = capsys.readouterr().out
    assert "dry-run: nothing was changed" in out
    assert "amerge_entities(" in out and "pre-check passed" in out
    assert _sha(rag_dir / GRAPHML_NAME) == before
    assert SOURCES <= _vdb_names(rag_dir)
    assert not (tmp_path / "backups").exists() and not (tmp_path / "apply-log.jsonl").exists()


def test_apply_backup_merge_rerun_and_restore(rag_dir, tmp_path, capsys):
    plan = _plan(rag_dir, tmp_path)
    graph_file = rag_dir / GRAPHML_NAME
    before_sha = _sha(graph_file)
    before_nodes = set(load_graph(rag_dir).nodes)

    assert main(_args(plan, rag_dir, tmp_path, "--yes")) == 0
    out = capsys.readouterr().out
    assert "backup:" in out and "done: 3 groups merged" in out
    backups = list((tmp_path / "backups").iterdir())
    assert len(backups) == 1 and (backups[0] / "manifest.json").is_file()
    after_nodes = set(load_graph(rag_dir).nodes)
    assert len(after_nodes) == len(before_nodes) - len(SOURCES)
    assert not (SOURCES & after_nodes)
    assert not (SOURCES & _vdb_names(rag_dir))  # the vector store was updated by LightRAG too
    log_lines = [json.loads(line) for line in (tmp_path / "apply-log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["status"] for e in log_lines] == ["done"] * 3

    # rerun: finished groups are skipped, exit 0, nothing new in the log, no second backup
    assert main(_args(plan, rag_dir, tmp_path, "--yes")) == 0
    assert "nothing to do" in capsys.readouterr().out
    assert len((tmp_path / "apply-log.jsonl").read_text(encoding="utf-8").splitlines()) == 3
    assert len(list((tmp_path / "backups").iterdir())) == 1

    # restore: the graph file is byte-identical to the state before apply
    assert main(["restore", str(backups[0]), "--working-dir", str(rag_dir), "--lang", "en"]) == 0
    assert "backup is intact" in capsys.readouterr().out
    assert _sha(graph_file) != before_sha  # dry-run of restore changed nothing yet
    assert main(["restore", str(backups[0]), "--working-dir", str(rag_dir), "--yes", "--lang", "en"]) == 0
    assert _sha(graph_file) == before_sha
    assert set(load_graph(rag_dir).nodes) == before_nodes

    # after the restore the sources are back, so the logged groups are applied again
    assert main(["apply", str(plan), "--working-dir", str(rag_dir), "--rag", FACTORY_SPEC, "--yes", "--no-backup", "--lang", "en"]) == 0
    assert not (SOURCES & set(load_graph(rag_dir).nodes))


def test_relation_weight_follows_lightrag_max_rule(rag_dir, tmp_path):
    plan = _plan(rag_dir, tmp_path)
    assert main(_args(plan, rag_dir, tmp_path, "--yes")) == 0
    edges = {frozenset((e.source, e.target)): e.weight for e in load_graph(rag_dir).edges}
    assert edges[frozenset(("OpenAI", "Sam Altman"))] == 2.0  # 3 relations, 2 distinct chunks


def test_limit_applies_first_groups_only(rag_dir, tmp_path):
    plan = _plan(rag_dir, tmp_path)
    assert main(_args(plan, rag_dir, tmp_path, "--yes", "--limit", "1", "--no-backup")) == 0
    nodes = set(load_graph(rag_dir).nodes)
    assert "openai" not in nodes and "삼성전자의" in nodes and "(주)카카오" in nodes


def test_stale_plan_aborts_before_any_merge(rag_dir, tmp_path, capsys):
    plan = _plan(rag_dir, tmp_path)
    data = json.loads(plan.read_text(encoding="utf-8"))
    data["groups"][2]["sources"].append("Ghost Entity")  # a node that is not in the graph
    plan.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    before = _sha(rag_dir / GRAPHML_NAME)
    vdb_before = _sha(rag_dir / "vdb_entities.json")
    # with --working-dir the check happens before the factory is even called ...
    assert main(_args(plan, rag_dir, tmp_path, "--yes", "--working-dir", str(rag_dir))) == 3
    assert "Ghost Entity" in capsys.readouterr().err
    # ... and without it, right after the factory told us where the data lives
    assert main(_args(plan, rag_dir, tmp_path, "--yes")) == 3
    assert _sha(rag_dir / GRAPHML_NAME) == before
    assert _sha(rag_dir / "vdb_entities.json") == vdb_before
    assert not (tmp_path / "backups").exists() and not (tmp_path / "apply-log.jsonl").exists()


def test_factory_errors_have_a_fix(rag_dir, tmp_path, capsys, sample_plan):
    for spec, text in [("nocolon", "Use FILE.py:FUNC"), (f"{FACTORY}:missing", "not callable"), (str(tmp_path / "nope.py") + ":f", "not found")]:
        assert main(["apply", str(sample_plan), "--rag", spec, "--yes", "--lang", "en"]) == 2
        assert text in capsys.readouterr().err


def test_restore_detects_tampered_backup(rag_dir, tmp_path):
    plan = _plan(rag_dir, tmp_path)
    assert main(_args(plan, rag_dir, tmp_path, "--yes")) == 0
    backup = next((tmp_path / "backups").iterdir())
    (backup / "data" / GRAPHML_NAME).write_text("tampered", encoding="utf-8")
    assert main(["restore", str(backup), "--working-dir", str(rag_dir), "--yes", "--lang", "en"]) == 2


def test_restore_leaves_new_files_unless_pruned(rag_dir, tmp_path, capsys):
    from lightrag_dedupe.backup import create_backup, restore_backup

    backup = create_backup(rag_dir, tmp_path / "b")
    (rag_dir / "created_later.json").write_text("{}", encoding="utf-8")
    assert restore_backup(backup, rag_dir).extra == ["created_later.json"]
    assert (rag_dir / "created_later.json").exists()
    restore_backup(backup, rag_dir, prune=True)
    assert not (rag_dir / "created_later.json").exists()


def test_restore_works_with_relative_paths(rag_dir, tmp_path, monkeypatch):
    from lightrag_dedupe.backup import create_backup, restore_backup

    backup = create_backup(rag_dir, tmp_path / "b")
    (rag_dir / GRAPHML_NAME).write_text("changed", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = restore_backup(backup.relative_to(tmp_path), "rag_storage")
    assert result.restored > 0 and result.extra == []
    assert _sha(rag_dir / GRAPHML_NAME) != hashlib.sha256(b"changed").hexdigest()
