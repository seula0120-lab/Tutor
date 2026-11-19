import json

from tutor import notice
from tutor.notice import exam_years, tax_changes, tax_notes, tax_notice


def write_bank(d, rnd, exam_date):
    (d / f"{rnd}.json").write_text(json.dumps({"round": rnd, "exam_date": exam_date, "theory": []}), encoding="utf-8")


def test_year_shown_only_when_exam_date_has_one(tmp_path):
    write_bank(tmp_path, 128, "2026-02-07")
    write_bank(tmp_path, 127, "2025년 12월 6일")
    write_bank(tmp_path, 126, None)
    write_bank(tmp_path, 125, "")
    write_bank(tmp_path, 124, "날짜 미상")
    assert tax_notice("세무회계", 128, tmp_path) == "128회(2026년 시행) · 세법 개정 확인 필요"
    assert tax_notice("세무회계", 127, tmp_path) == "127회(2025년 시행) · 세법 개정 확인 필요"
    for rnd in (126, 125, 124, 99):                                   # 정보 없음 → 회차만, 연도를 짐작하지 않는다
        assert tax_notice("세무회계", rnd, tmp_path) == f"{rnd}회 · 세법 개정 확인 필요"
    assert tax_notice("재무회계", 128, tmp_path) is None and tax_notice("원가회계", 128, tmp_path) is None


def test_real_bank_has_no_dates_so_no_year_is_invented():
    assert exam_years() == {}
    assert tax_notice("세무회계", 128) == "128회 · 세법 개정 확인 필요"


def test_cache_follows_file_changes(tmp_path):
    write_bank(tmp_path, 10, None)
    assert tax_notice("세무회계", 10, tmp_path) == "10회 · 세법 개정 확인 필요"
    write_bank(tmp_path, 10, "2024-05-11")
    assert "2024년 시행" in tax_notice("세무회계", 10, tmp_path)


def test_tax_changes_file_is_empty_list():
    assert json.loads(notice.TAX_CHANGES.read_text(encoding="utf-8")) == []
    assert tax_changes() == []


def test_memo_shown_when_keyword_in_text(tmp_path):
    path = tmp_path / "tc.json"
    path.write_text(json.dumps([{"year": 2025, "tax": "소득세", "keyword": "기본공제", "memo": "공제액 확인"},
                                {"year": 2025, "tax": "법인세", "keyword": "접대비", "memo": "한도 확인"}]), encoding="utf-8")
    kw = dict(bank_dir=tmp_path, changes_path=path)
    notes = tax_notes("세무회계", 5, "기본공제 대상자는?", "소득세", **kw)
    assert notes == ["5회 · 세법 개정 확인 필요", "2025년 세법 개정: 공제액 확인"]
    assert tax_notes("세무회계", 5, "기본공제 대상자는?", "법인세", **kw) == ["5회 · 세법 개정 확인 필요"]   # 세목이 다르면 안 붙는다
    assert len(tax_notes("세무회계", 5, "관계없는 문제", "소득세", **kw)) == 1
    assert tax_notes("재무회계", 5, "기본공제", "소득세", **kw) == []


def test_bad_changes_file_is_ignored(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{ not json", encoding="utf-8")
    assert tax_changes(path) == []
    path.write_text('{"a": 1}', encoding="utf-8")
    assert tax_changes(path) == []


def test_public_question_carries_notes(conn):
    from tutor.quiz import public_question
    rows = conn.execute("SELECT * FROM questions WHERE subject = '세무회계'").fetchall()
    q = public_question(rows[0])
    assert q["tax_notes"][0].endswith("세법 개정 확인 필요")
    fin = public_question(conn.execute("SELECT * FROM questions WHERE subject = '재무회계'").fetchone())
    assert fin["tax_notes"] == [] and fin["tax_notice"] is None
