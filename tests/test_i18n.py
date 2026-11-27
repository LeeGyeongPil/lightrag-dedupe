"""AC-8: two-language UI, language precedence, identical key sets."""
import json
import re
from pathlib import Path

import pytest
from conftest import ALIASES, ROOT, SAMPLE_GRAPH_DIR

from lightrag_dedupe.cli import main
from lightrag_dedupe.i18n import Translator, load_table, resolve_lang

SRC = ROOT / "src" / "lightrag_dedupe"
# Keys built at run time (f-strings in report.py) are listed here so they are checked too.
DYNAMIC_KEYS = {
    "flag.type_conflict", "flag.near",
    "rule.nfkc", "rule.casefold", "rule.suffix", "rule.ko_particle", "rule.punct_space", "rule.alias", "rule.guard_too_short",
    "explain.particle_graph", "explain.particle_alias",
    "restore.extra", "restore.pruned",
}


def test_key_sets_are_identical():
    en, ko = load_table("en"), load_table("ko")
    assert set(en) == set(ko)
    assert all(v.strip() for v in en.values()) and all(v.strip() for v in ko.values())


def test_placeholders_match_between_languages():
    en, ko = load_table("en"), load_table("ko")
    pattern = re.compile(r"\{(\w+)\}")
    for key in en:
        assert set(pattern.findall(en[key])) == set(pattern.findall(ko[key])), key


def test_json_files_have_no_duplicate_keys():
    for lang in ("en", "ko"):
        pairs = json.loads((SRC / "locales" / f"{lang}.json").read_text(encoding="utf-8"), object_pairs_hook=lambda p: p)
        keys = [k for k, _ in pairs]
        assert len(keys) == len(set(keys)), lang


def test_every_key_used_in_code_exists_and_every_key_is_used():
    used = set(DYNAMIC_KEYS)
    for py in SRC.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        used |= set(re.findall(r"\btr\(\s*[\"']([\w.]+)[\"']", text))
        used |= set(re.findall(r"Error\(\s*\"([\w.]+)\"", text))
    table = load_table("en")
    assert used - set(table) == set(), "keys used in code but missing from the table"
    assert set(table) - used == set(), "keys in the table that no code uses"


@pytest.mark.parametrize(
    ("cli", "env", "expected"),
    [
        ("ko", {"LIGHTRAG_DEDUPE_LANG": "en"}, "ko"),
        ("en", {"LIGHTRAG_DEDUPE_LANG": "ko"}, "en"),
        (None, {"LIGHTRAG_DEDUPE_LANG": "ko", "LC_ALL": "en_US.UTF-8"}, "ko"),
        (None, {"LIGHTRAG_DEDUPE_LANG": "en", "LC_ALL": "ko_KR.UTF-8"}, "en"),
        (None, {"LC_ALL": "ko_KR.UTF-8", "LC_MESSAGES": "en_US", "LANG": "en_US"}, "ko"),
        (None, {"LC_ALL": "C", "LC_MESSAGES": "ko_KR", "LANG": "ko_KR"}, "en"),
        (None, {"LC_MESSAGES": "ko_KR.UTF-8", "LANG": "en_US"}, "ko"),
        (None, {"LANG": "ko_KR.UTF-8"}, "ko"),
        (None, {"LANG": "ja_JP.UTF-8"}, "en"),
        (None, {"LANG": ""}, "en"),
        (None, {}, "en"),
        (None, {"LIGHTRAG_DEDUPE_LANG": "fr", "LANG": "ko_KR"}, "en"),
    ],
)
def test_language_precedence(cli, env, expected):
    assert resolve_lang(cli, env) == expected


def test_translator_falls_back_and_formats():
    tr = Translator("ko")
    assert tr("scan.wrote", path="x") == "x 에 썼습니다"
    assert Translator("xx").lang == "en"
    assert tr("no.such.key") == "no.such.key"


def test_help_switches_language(capsys):
    assert main(["--help", "--lang", "ko"]) == 0
    ko = capsys.readouterr().out
    assert main(["--help", "--lang", "en"]) == 0
    en = capsys.readouterr().out
    assert "사용법" in ko and "명령" in ko and "usage" not in ko.lower().replace("lightrag-dedupe", "")
    assert "usage" in en and "commands" in en and "사용법" not in en
    assert main(["scan", "--help", "--lang", "ko"]) == 0
    assert "읽기만" in capsys.readouterr().out
    assert main(["scan", "--lang", "ko", "--help"]) == 0
    assert "옵션" in capsys.readouterr().out


def test_scan_summary_and_errors_in_both_languages(tmp_path, capsys):
    for lang, groups, review, missing in [("en", "groups:", "review:", "graph file not found"), ("ko", "묶음:", "검토:", "그래프 파일을 찾을 수 없습니다")]:
        out = tmp_path / f"{lang}.json"
        assert main(["scan", str(SAMPLE_GRAPH_DIR), "--out", str(out), "--aliases", str(ALIASES), "--lang", lang]) == 0
        text = capsys.readouterr().out
        assert groups in text and review in text
        assert main(["scan", str(tmp_path / "none"), "--lang", lang]) == 2
        assert missing in capsys.readouterr().err


def test_environment_variable_and_locale_drive_the_cli(tmp_path, capsys, monkeypatch):
    out = tmp_path / "p.json"
    base = ["scan", str(SAMPLE_GRAPH_DIR), "--out", str(out)]
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")
    assert main(base) == 0
    assert "묶음:" in capsys.readouterr().out
    monkeypatch.setenv("LIGHTRAG_DEDUPE_LANG", "en")
    assert main(base) == 0
    assert "groups:" in capsys.readouterr().out
    assert main([*base, "--lang", "ko"]) == 0
    assert "묶음:" in capsys.readouterr().out


def test_explain_in_both_languages(capsys):
    args = ["explain", "오픈AI의", "--in", str(SAMPLE_GRAPH_DIR), "--aliases", str(ALIASES)]
    assert main([*args, "--lang", "en"]) == 0
    en = capsys.readouterr().out
    assert "ko_particle:의" in en and "alias table" in en and "key: openai" in en and "- OpenAI" in en
    assert main([*args, "--lang", "ko"]) == 0
    ko = capsys.readouterr().out
    assert "별칭표" in ko and "키: openai" in ko
    assert main(["explain", "no such node", "--in", str(SAMPLE_GRAPH_DIR), "--lang", "en"]) == 2
    assert "exactly as stored" in capsys.readouterr().err


def test_explain_guard_and_no_steps(capsys):
    assert main(["explain", "Co", "--in", str(SAMPLE_GRAPH_DIR), "--lang", "en"]) == 0
    assert "guard:too_short" in capsys.readouterr().out
    assert main(["explain", "마이크로", "--in", str(SAMPLE_GRAPH_DIR), "--lang", "en"]) == 0
    assert "no rule changed this name" in capsys.readouterr().out


def test_demo_and_restore_messages_exist_in_both_languages():
    for lang in ("en", "ko"):
        table = load_table(lang)
        assert Path  # keep import used
        assert "practice" in table["demo.banner"].lower() or "목" in table["demo.banner"]
