"""AC-4: human edits to the plan are honored; invalid plans are rejected with exit code 2."""
import csv
import json
from pathlib import Path

import pytest
from conftest import ALIASES, SAMPLE_GRAPH_DIR

from lightrag_dedupe.aliases import load_aliases
from lightrag_dedupe.candidates import scan_graph
from lightrag_dedupe.cli import main
from lightrag_dedupe.errors import UsageError
from lightrag_dedupe.graphml import load_graph
from lightrag_dedupe.plan import FORMAT, CSV_COLUMNS, load_plan, write_plan_csv


@pytest.fixture
def plan_csv(tmp_path: Path) -> Path:
    plan = scan_graph(load_graph(SAMPLE_GRAPH_DIR), load_aliases(ALIASES))
    path = tmp_path / "plan.csv"
    write_plan_csv(plan, path)
    return path


def _edit(path: Path, change) -> None:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        change(row)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_csv_columns_are_english_and_fixed(plan_csv):
    header = plan_csv.read_text(encoding="utf-8-sig").splitlines()[0]
    assert header == ",".join(CSV_COLUMNS)


def test_default_csv_applies_only_auto_groups(plan_csv):
    loaded = load_plan(plan_csv)
    assert sorted(m.target for m in loaded.merges) == ["OpenAI", "삼성전자", "카카오"]
    assert loaded.skipped == 2  # type conflict + review pair
    assert loaded.graph_sha256 is None


def test_apply_false_drops_a_group(plan_csv):
    _edit(plan_csv, lambda r: r.update(apply="false") if r["group_id"] == "G002" else None)
    assert "OpenAI" not in [m.target for m in load_plan(plan_csv).merges]


def test_changed_target_is_used(plan_csv):
    _edit(plan_csv, lambda r: r.update(target="Samsung Electronics") if r["group_id"] == "G003" else None)
    merge = next(m for m in load_plan(plan_csv).merges if m.id == "G003")
    assert merge.target == "Samsung Electronics"
    assert sorted(merge.sources) == ["Samsung Electronics Co., Ltd.", "삼성전자", "삼성전자의"]


def test_target_switched_to_another_member(plan_csv):
    _edit(plan_csv, lambda r: r.update(target="openai") if r["group_id"] == "G002" else None)
    merge = next(m for m in load_plan(plan_csv).merges if m.id == "G002")
    assert merge.target == "openai" and "OpenAI" in merge.sources and "openai" not in merge.sources


def test_review_row_set_true_is_included(plan_csv):
    _edit(plan_csv, lambda r: r.update(apply="true") if r["group_id"] == "R001" else None)
    merge = next(m for m in load_plan(plan_csv).merges if m.id == "R001")
    assert (merge.target, merge.sources) == ("OpenAI", ("OpenAl",))


def test_json_edit_is_honored(sample_plan):
    data = json.loads(sample_plan.read_text(encoding="utf-8"))
    data["review"][0]["apply"] = True
    data["groups"][1]["apply"] = False
    sample_plan.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    loaded = load_plan(sample_plan)
    assert [m.id for m in loaded.merges] == ["G003", "G004", "R001"]
    assert loaded.graph_sha256 == data["graph_sha256"]


def _rewrite(path: Path, change) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(format="lightrag-dedupe/plan@99"), "unsupported plan format"),
        (lambda d: d["groups"][1].update(sources=[]), "no source names"),
        (lambda d: d["groups"][1].update(sources=["openai", "OpenAI"]), "also listed as a source"),
        (lambda d: d["groups"][2].update(sources=d["groups"][1]["sources"]), "used by both"),
        (lambda d: d["groups"][1].update(apply="maybe"), "true or false"),
        (lambda d: d["groups"][1].update(target=" "), "target is empty"),
    ],
)
def test_invalid_json_plans_exit_2(sample_plan, capsys, change, message):
    _rewrite(sample_plan, change)
    assert main(["apply", str(sample_plan), "--working-dir", str(SAMPLE_GRAPH_DIR), "--lang", "en"]) == 2
    assert message in capsys.readouterr().err


def test_missing_and_garbled_plan_files(tmp_path, capsys):
    assert main(["apply", str(tmp_path / "nope.json"), "--lang", "en"]) == 2
    assert "Run scan first" in capsys.readouterr().err
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert main(["apply", str(bad), "--lang", "en"]) == 2


def test_csv_errors(plan_csv):
    _edit(plan_csv, lambda r: r.update(apply="true") if r["group_id"] == "G002" and r["role"] == "source" and r["member"] == "openai" else None)
    _edit(plan_csv, lambda r: r.update(apply="false") if r["group_id"] == "G002" and r["member"] == "OpenAI" else None)
    with pytest.raises(UsageError) as exc:
        load_plan(plan_csv)
    assert exc.value.key == "err.plan_csv_inconsistent"


def test_csv_missing_columns(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("group_id,member\nG1,a\n", encoding="utf-8")
    with pytest.raises(UsageError) as exc:
        load_plan(p)
    assert exc.value.key == "err.plan_csv_columns"


def test_csv_group_with_single_member_is_rejected(plan_csv):
    p = plan_csv.parent / "one.csv"
    p.write_text("group_id,apply,target,member\nG1,true,A,A\n", encoding="utf-8")
    with pytest.raises(UsageError) as exc:
        load_plan(p)
    assert exc.value.key == "err.plan_empty_sources"


def test_format_constant_matches_written_plan(sample_plan):
    assert json.loads(sample_plan.read_text(encoding="utf-8"))["format"] == FORMAT
