"""AC-9: the practice-mock demo reproduces a real LightRAG merge offline."""
import re
import time

from lightrag_dedupe.cli import main


def test_demo_en(capsys):
    start = time.perf_counter()
    assert main(["demo", "--lang", "en"]) == 0
    assert time.perf_counter() - start < 60
    out = capsys.readouterr().out
    assert "practice mock" in out
    m = re.search(r"nodes: (\d+) -> (\d+)", out)
    assert m and int(m.group(2)) < int(m.group(1))
    assert "OpenAI -> Sam Altman: 3 relations became 1, weight 2.0" in out
    assert "(0 merged-away names left)" in out  # LightRAG updated its vector store as well


def test_demo_ko(capsys):
    assert main(["demo", "--lang", "ko"]) == 0
    out = capsys.readouterr().out
    assert "연습용 목(MOCK)" in out
    assert "OpenAI -> Sam Altman: 관계 3개가 1개로, 가중치 2.0" in out


def test_demo_never_touches_the_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["demo", "--lang", "en"]) == 0
    assert list(tmp_path.iterdir()) == []
