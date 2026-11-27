"""AC-1: normalization rules follow the edge-case table; rule codes are kept in order."""
import pytest

from lightrag_dedupe.normalize import normalize_name

# (name, known graph keys, aliases, expected key, expected rule codes in order)
CASES = [
    ("Samsung Electronics Co., Ltd.", (), None, "samsungelectronics", ["casefold", "suffix:ltd", "suffix:co", "punct_space"]),
    ("Co", (), None, "co", ["casefold", "guard:too_short"]),
    ("(주)카카오", (), None, "카카오", ["suffix:(주)"]),
    ("주식회사 카카오", (), None, "카카오", ["suffix:주식회사"]),
    ("카카오", (), None, "카카오", []),
    ("카카오(주)", (), None, "카카오", ["suffix:(주)"]),
    ("ＯｐｅｎＡＩ", (), None, "openai", ["nfkc", "casefold"]),
    ("삼성전자의", ("삼성전자",), None, "삼성전자", ["ko_particle:의"]),
    ("삼성전자의", (), None, "삼성전자의", []),  # no graph evidence: keep the particle
    ("마이크로", (), None, "마이크로", []),
    ("마이크로", ("마이크로소프트",), None, "마이크로", []),  # stem 마이크 is not a node
    ("마이크로", ("마이크",), None, "마이크", ["ko_particle:로"]),  # stem exists: rule fires
    ("오픈AI의", (), {"오픈ai": "openai"}, "openai", ["casefold", "ko_particle:의", "alias"]),
    ("OpenAI Inc.", (), None, "openai", ["casefold", "suffix:inc"]),
    ("Open AI", (), None, "openai", ["casefold", "punct_space"]),
    ("Acme Corp", (), None, "acme", ["casefold", "suffix:corp"]),
    ("Inc", (), None, "inc", ["casefold", "guard:too_short"]),
    ("X Inc", (), None, "xinc", ["casefold", "guard:too_short", "punct_space"]),
    ("---", (), None, "", ["punct_space"]),
    ("Samsung Electronics", (), {"samsungelectronics": "삼성전자"}, "삼성전자", ["casefold", "punct_space", "alias"]),
]


@pytest.mark.parametrize(("name", "known", "aliases", "key", "rules"), CASES)
def test_edge_cases(name, known, aliases, key, rules):
    result = normalize_name(name, known, aliases)
    assert result.key == key
    assert list(result.rules) == rules


def test_surface_rules_ignore_casefold_only():
    assert normalize_name("openai").surface_rules == ()
    assert normalize_name("OpenAI Inc.").surface_rules == ("suffix:inc",)


def test_particle_needs_two_letter_stem():
    # "아이" would become "아" (1 letter) even if "아" were a node: never strip down to one letter.
    assert normalize_name("아이", ("아",)).key == "아이"


def test_steps_carry_particle_evidence():
    graph = normalize_name("삼성전자의", ("삼성전자",))
    alias = normalize_name("오픈AI의", (), {"오픈ai": "openai"})
    assert [s.detail for s in graph.steps if s.rule.startswith("ko_particle")] == ["graph"]
    assert [s.detail for s in alias.steps if s.rule.startswith("ko_particle")] == ["alias"]
