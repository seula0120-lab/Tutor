"""검색 잡음 규칙: 흔한 낱말 감점과 꼬리 제거(일반 규칙. 특정 질문용 처리 없음)."""
from conftest import C4, item
from tutor import search
from tutor.bank import load_bank
from tutor.db import connect
from tutor.search import search_theory


def _noise_conn(tmp_path):
    conn = connect(tmp_path / "noise.db")
    # '항목' 은 문항 대부분에 나오는 흔한 낱말, '조정합계표' 는 한 문항에만 나오는 희귀한 낱말
    items = [item(1, "소득금액조정합계표 항목에 대한 설명으로 옳은 것은?", C4, "1")]
    items += [item(n, f"다음 항목 {n}번에 대한 설명으로 옳은 것은?", C4, "1") for n in range(2, 15)]
    load_bank(conn, [(1, items)])
    return conn


def test_common_word_only_results_are_cut_from_the_tail(tmp_path):
    conn = _noise_conn(tmp_path)
    result = search_theory("소득금액조정합계표 항목", conn, entries=[])
    assert [r["id"] for r in result["results"]] == ["1-1"]


def test_cut_and_damp_can_be_switched_off(tmp_path, monkeypatch):
    conn = _noise_conn(tmp_path)
    monkeypatch.setattr(search, "COMMON_DAMP", 1.0)
    monkeypatch.setattr(search, "TAIL_CUT", 0.0)
    result = search_theory("소득금액조정합계표 항목", conn, entries=[])
    assert len(result["results"]) > 1          # 규칙을 끄면 '항목' 만 맞은 문항이 꼬리에 붙는다


def test_rare_word_still_wins_over_common_word(tmp_path):
    conn = _noise_conn(tmp_path)
    result = search_theory("항목 소득금액조정합계표", conn, entries=[])
    assert result["results"][0]["id"] == "1-1"
