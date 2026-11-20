"""강사님 피드백 ②: 시행일(exam_dates)·개정 전 기준 배지(amend)·수치 구조(numbers)·문항 속 표(tables)."""
import copy
import json
from datetime import date
from pathlib import Path

import pytest

from tutor import amend, exam_dates, notice, numbers, tables
from tutor.bank import load_bank
from tutor.db import connect

ROOT = Path(__file__).resolve().parent.parent
STUDY = ROOT / "data" / "study" / "세무회계"
TAX_NOTES = sorted(STUDY.glob("*/*.json"))


def ordinal(y, m, d):
    return date(y, m, d).toordinal()


# ── 시행일 ──────────────────────────────────────────────
def test_exam_dates_file_has_source_for_every_round():
    found = exam_dates.read()
    assert len(found) == 36
    for round_no, entry in found.items():
        assert entry["exam_date"] and entry["source"], round_no
        assert Path(entry["source"]).exists() or "PJT2" in entry["source"], round_no          # 읽은 원본 파일 경로
        assert entry["page"] is not None or "HWP" in entry["location"], round_no                  # PDF 는 쪽 번호, HWP 는 쪽이 없다고 적음


def test_exam_dates_loaded_into_db_and_missing_rounds_stay_empty(tmp_path):
    path = tmp_path / "dates.json"
    path.write_text(json.dumps([{"round": 1, "exam_date": "2024-02-10", "source": "a.pdf", "page": 1}]), encoding="utf-8")
    conn = connect(tmp_path / "d.db")
    item = {"id": "1-1", "number": 1, "form": "A", "kind": "x", "question": "q", "choices": ["a", "b"], "answer": "1", "explanation": "", "points": 3}
    load_bank(conn, [(1, [item]), (2, [{**item, "id": "2-1"}])], exam_dates_path=path)
    rows = {r["round"]: r["exam_date"] for r in conn.execute("SELECT round, exam_date FROM exam_dates")}
    assert rows == {1: "2024-02-10"}                                         # 2회는 파일에 없으니 줄이 없다(지어내지 않음)
    conn.close()


def test_recent_rule_is_date_based_for_dated_rounds_and_old_rule_otherwise():
    days = {10: ordinal(2020, 1, 1), 11: ordinal(2024, 6, 1), 12: ordinal(2025, 12, 1)}
    assert exam_dates.is_recent(12, 12, days) and exam_dates.is_recent(11, 12, days)
    assert not exam_dates.is_recent(10, 12, days)                            # 날짜가 18개월보다 오래됨
    assert exam_dates.is_recent(5, 12, days) is True and exam_dates.is_recent(2, 12, days) is False   # 시행일이 없는 회차는 옛 규칙(회차 > 12-10)
    assert exam_dates.is_recent(5, 12, {}) is True and exam_dates.is_recent(2, 12, {}) is False
    assert exam_dates.label(ordinal(2026, 10, 3)) == "2026년 10월 시행 시험 기준"


def test_real_recent_set_matches_the_old_last_ten_rounds():
    days = {n: date.fromisoformat(e["exam_date"]).toordinal() for n, e in exam_dates.read().items()}
    recent = {n for n in days if exam_dates.is_recent(n, max(days), days)}
    assert recent == set(range(119, 129))


def test_exam_basis_label_only_for_tax_with_known_date():
    assert notice.exam_basis("세무회계", 128) == "2026년 10월 시행 시험 기준"
    assert notice.exam_basis("재무회계", 128) is None
    assert notice.exam_basis("세무회계", 99) is None


# ── 개정 전 기준 ─────────────────────────────────────────
def test_apply_day_reads_leading_date_only():
    assert amend.apply_day("’26.1.1. 이후 개시하는 사업연도분부터") == ordinal(2026, 1, 1)
    assert amend.apply_day("’26.7.1. 이후 퇴직하여") == ordinal(2026, 7, 1)
    assert amend.apply_day("개정 시행령 적용") is None and amend.apply_day("시행 유예") is None


def test_pre_amend_badge_needs_earlier_exam_same_unit_and_keyword():
    text = "법인세 세율은 과세표준 2억원 이하 9%이다."
    before = amend.badges("과세표준·신고납부", text, ordinal(2025, 6, 1))
    assert [b["label"] for b in before] == ["개정 전 기준"] and "법인세 세율" in before[0]["what"] and "p26" in before[0]["text"]
    assert amend.badges("과세표준·신고납부", text, ordinal(2026, 10, 3)) == []        # 적용일 뒤 시험
    assert amend.badges("손금·익금", text, ordinal(2025, 6, 1)) == []                 # 다른 단원
    assert amend.badges("과세표준·신고납부", "결손금 이월공제 기간은 15년이다.", ordinal(2025, 6, 1)) == []   # 키워드 없음
    assert amend.badges("과세표준·신고납부", text, None) == []                        # 시행일을 모르면 배지 없음


def test_every_dated_change_has_keywords_so_no_change_is_silently_unmatched():
    for path in TAX_NOTES:
        for change in json.loads(path.read_text(encoding="utf-8"))["changes"]:
            if amend.apply_day(change["when"]) is not None:
                assert change["keywords"], (path.name, change["what"])


# ── 수치 구조 ────────────────────────────────────────────
@pytest.mark.parametrize("text, expect", [
    ("납부할 세액이 1천만원을 초과하면", [("1천만", "원")]),
    ("1천 5백만원 이하", [("1천 5백만", "원")]),
    ("세율은 9%→10%, 3천억원 초과 24%", [("9", "%"), ("10", "%"), ("3천억", "원"), ("24", "%")]),
    ("’26.1.1. 이후 개시하는 사업연도분부터(법인법 §24③, 제3항)", []),        # 날짜·조문은 수치가 아니다
    ("10만원 초과 20만원 이하 15% → 40%", [("10만", "원"), ("20만", "원"), ("15", "%"), ("40", "%")]),
])
def test_number_finder_values_and_units(text, expect):
    assert [(n["value"], n["unit"]) for n in numbers.find(text)] == expect


@pytest.mark.parametrize("path", TAX_NOTES, ids=lambda p: p.stem)
def test_every_number_in_tax_note_sentences_is_structured(path):
    note = json.loads(path.read_text(encoding="utf-8"))
    assert numbers.problems(note) == []


def test_total_structured_numbers_and_all_fields_present():
    items = [i for p in TAX_NOTES for i in json.loads(p.read_text(encoding="utf-8"))["numbers"]]
    assert len(items) >= 150
    for item in items:
        assert {"value", "unit", "applies_to", "as_of", "exception", "source", "where", "token"} <= set(item)


def _note_with_number():
    path = next(p for p in TAX_NOTES if p.stem == "과세표준·신고납부")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("field", ["unit", "source", "applies_to", "as_of", "value"])
def test_missing_field_fails(field):
    note = _note_with_number()
    note["numbers"][0][field] = ""
    assert any(field in p for p in numbers.problems(note))


def test_removed_number_and_missing_amendment_page_fail():
    note = _note_with_number()
    removed = note["numbers"].pop(0)
    assert any(removed["token"] in p for p in numbers.problems(note))
    note = _note_with_number()
    change_item = next(i for i in note["numbers"] if i["where"].startswith("changes["))
    change_item["page"] = None
    assert any("쪽 번호" in p for p in numbers.problems(note))
    note = _note_with_number()
    next(i for i in note["numbers"] if i["where"].startswith("changes["))["as_of"] = ""
    assert any("as_of" in p for p in numbers.problems(note))              # 적용 시기가 없는 개정 항목 수치


def test_change_numbers_carry_application_period_and_page():
    for path in TAX_NOTES:
        note = json.loads(path.read_text(encoding="utf-8"))
        changes = note["changes"]
        for item in (i for i in note["numbers"] if i["where"].startswith("changes[")):
            idx = int(item["where"].split("[")[1].split("]")[0])
            assert item["as_of"] == changes[idx]["when"] and item["page"] == changes[idx]["page"], (path.stem, item["token"])
            assert item["source"].endswith(f"p{changes[idx]['page']}")


# ── 표 ─────────────────────────────────────────────────
def test_real_tables_are_well_formed_and_belong_to_existing_questions():
    data = json.loads(tables.PATH.read_text(encoding="utf-8"))
    assert len(data["tables"]) >= 60
    bank_ids = {f"{p.stem}-{q['number']}" for p in (ROOT / "data" / "bank").glob("*.json") for q in json.loads(p.read_text(encoding="utf-8"))["theory"]} \
        if (ROOT / "data" / "bank").is_dir() else None
    for t in data["tables"]:
        assert 0 <= t["header_rows"] < t["n_rows"] or t["header_rows"] == 0
        for c in t["cells"]:
            assert 0 <= c["r"] and c["r"] + c["rs"] <= t["n_rows"] and 0 <= c["c"] and c["c"] + c["cs"] <= t["n_cols"], t["id"]
        if bank_ids is not None:
            assert t["id"] in bank_ids, t["id"]
    assert all(u["reason"] for u in data["unmatched"])                       # 못 바꾼 표는 사유와 함께 목록으로


def test_table_keeps_header_and_merged_cells():
    (t,) = tables.for_question("123-8")
    top = {c["text"]: c for c in t["cells"] if c["r"] == 0}
    assert t["header_rows"] == 2 and t["row_header"] is True
    assert top["보조부문"]["cs"] == 2 and top["제조부문"]["cs"] == 2 and top["배분대상원가"]["rs"] == 2
    body = {(c["r"], c["c"]): c["text"] for c in t["cells"]}
    assert body[(2, 0)] == "수선부문" and body[(2, 5)] == "200,000원"
    (t,) = tables.for_question("128-4")
    assert [c["text"] for c in t["cells"] if c["r"] == 0] == ["공사명", "도급금액", "착공일자", "준공일자"]
    assert "3,000,000,000원" in [c["text"] for c in t["cells"]]              # 쉼표가 따로 떨어져 찍힌 숫자를 바로잡는다


def test_public_question_carries_tables_and_badges(tmp_path):
    from tutor import quiz
    conn = connect(tmp_path / "t.db")
    item = {"id": "128-4", "number": 4, "form": "A", "kind": "x", "question": "공사 표", "choices": ["가", "나"], "answer": "1", "explanation": "", "points": 3}
    load_bank(conn, [(128, [item])], exam_dates_path=tmp_path / "none.json")
    q = quiz.public_question(quiz.get_row(conn, "128-4"))
    assert q["tables"] and q["tables"][0]["n_cols"] == 4
    assert q["exam_basis"] is None                                            # 이 문항은 재무회계
    conn.close()


def test_ox_old_tax_follows_exam_dates_when_present(tmp_path):
    from test_ox_review_daily import by_text, OLD, NEW
    from tutor import ox
    conn = connect(tmp_path / "o.db")
    load_bank(conn, [(1, OLD), (12, NEW)], exam_dates_path=tmp_path / "none.json")
    ox._cache.clear()
    assert by_text(conn, "근로소득 첫째")["old_tax"] is True                  # 시행일이 없으면 옛 규칙(1회 <= 12-10)
    with conn:
        conn.executemany("INSERT INTO exam_dates(round, exam_date, source, page) VALUES (?,?,?,?)",
                         [(1, "2025-04-12", "a", 1), (12, "2025-12-06", "b", 1)])
    ox._cache.clear()
    item = by_text(conn, "근로소득 첫째")
    assert item["old_tax"] is False                                         # 시행일이 18개월 안이라 최근
    assert item["exam_basis"] == ""                                         # 화면 문구는 data/exam_dates.json(진짜 시행일)에서만 만든다
    conn.close()
