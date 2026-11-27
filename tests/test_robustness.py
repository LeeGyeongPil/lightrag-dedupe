"""Round-2 regressions: usage line, translated argparse errors, non-UTF-8 CSV, unwritable --out."""
import pytest
from conftest import SAMPLE_GRAPH_DIR

from lightrag_dedupe.apply_python import load_factory
from lightrag_dedupe.cli import main
from lightrag_dedupe.errors import UsageError


@pytest.mark.parametrize(("lang", "word"), [("en", "usage"), ("ko", "사용법")])
def test_usage_prefix_appears_once(lang, word, capsys):
    assert main(["scan", "--help", "--lang", lang]) == 0
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith(f"{word}: lightrag-dedupe scan")
    assert first.count(word) == 1
    assert main(["scan", "--lang", lang]) == 2
    err = capsys.readouterr().err
    assert err.splitlines()[0].startswith(f"{word}: lightrag-dedupe scan")
    assert err.count(f"{word}: ") == 1


def test_argparse_errors_are_translated(capsys):
    assert main(["scan", "--lang", "ko"]) == 2
    err = capsys.readouterr().err
    assert "오류: 다음 인자가 필요합니다: path" in err
    assert main(["scan", "--lang", "en"]) == 2
    assert "error: the following arguments are required: path" in capsys.readouterr().err
    assert main(["scan", str(SAMPLE_GRAPH_DIR), "--near", "abc", "--lang", "ko"]) == 2
    assert "잘못된 숫자 값: 'abc'" in capsys.readouterr().err
    assert main(["scan", str(SAMPLE_GRAPH_DIR), "--max-review", "x", "--lang", "en"]) == 2
    assert "invalid integer value: 'x'" in capsys.readouterr().err
    assert main(["scan", str(SAMPLE_GRAPH_DIR), "--out", "--lang", "ko"]) == 2
    assert "값이 하나 필요합니다" in capsys.readouterr().err
    assert main(["scan", str(SAMPLE_GRAPH_DIR), "--bogus", "--lang", "ko"]) == 2
    assert "알 수 없는 인자: --bogus" in capsys.readouterr().err
    assert main(["demo", "--lang", "xx"]) == 2
    assert "invalid choice" in capsys.readouterr().err


def test_cp949_plan_csv_is_rejected_with_a_fix(tmp_path, capsys):
    plan = tmp_path / "plan.csv"
    plan.write_bytes("group_id,apply,target,member\ng1,true,삼성전자,삼성 전자\n".encode("cp949"))
    for lang, hint in (("en", "CSV UTF-8"), ("ko", "CSV UTF-8")):
        assert main(["apply", str(plan), "--working-dir", str(tmp_path), "--lang", lang]) == 2
        err = capsys.readouterr().err
        assert hint in err and "Traceback" not in err


def test_non_utf8_aliases_is_rejected(tmp_path, capsys):
    aliases = tmp_path / "a.csv"
    aliases.write_bytes("오픈AI,OpenAI\n".encode("cp949"))
    assert main(["scan", str(SAMPLE_GRAPH_DIR), "--out", str(tmp_path / "p.json"), "--aliases", str(aliases), "--lang", "en"]) == 2
    assert "not UTF-8" in capsys.readouterr().err


def test_unwritable_out_paths_exit_2(tmp_path, capsys):
    bad = tmp_path / "nonexistent" / "p.json"
    assert main(["scan", str(SAMPLE_GRAPH_DIR), "--out", str(bad), "--lang", "en"]) == 2
    assert "cannot write" in capsys.readouterr().err
    assert main(["scan", str(SAMPLE_GRAPH_DIR), "--out", str(tmp_path / "p.json"), "--csv", str(bad.with_suffix(".csv")), "--lang", "ko"]) == 2
    assert "쓸 수 없습니다" in capsys.readouterr().err


def test_plan_csv_has_bom_and_round_trips(tmp_path):
    out = tmp_path / "p.csv"
    assert main(["scan", str(SAMPLE_GRAPH_DIR), "--out", str(tmp_path / "p.json"), "--csv", str(out), "--lang", "en"]) == 0
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")
    from lightrag_dedupe.plan import load_plan

    assert load_plan(out).merges


def test_factory_import_hint_depends_on_missing_module(tmp_path):
    user = tmp_path / "f_user.py"
    user.write_text("import not_installed_embedder_xyz\ndef build():\n    pass\n", encoding="utf-8")
    with pytest.raises(UsageError) as exc:
        load_factory(f"{user}:build")
    assert exc.value.key == "err.factory_import_user" and exc.value.params["module"] == "not_installed_embedder_xyz"
    own = tmp_path / "f_lr.py"
    own.write_text("import lightrag_missing_check\n", encoding="utf-8")
    lr = tmp_path / "f_lr2.py"
    lr.write_text("import lightrag.nope_not_there\n", encoding="utf-8")
    with pytest.raises(UsageError) as exc:
        load_factory(f"{lr}:build")
    assert exc.value.key in ("err.factory_import", "err.factory_import_user")
