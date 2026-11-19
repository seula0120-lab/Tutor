import json
import os
import shutil
from pathlib import Path

from pdf_factory import make_answer_pdf
from tutor.answer_lines import _HtmlLines
from tutor.bank import BANK_DIR, load_bank, read_bank_files
from tutor.db import ROOT, connect
from tutor.search import scope_rounds, search_theory
from tutor.sync import CONVERTED, FAILED, UP_TO_DATE, format_report, list_raw_rounds, sync_raw

REAL_RAW = ROOT / "data" / "raw"
CONTENT_FIELDS = ("question", "choices", "answer", "explanation")


def raw_round(raw_dir, round_no, **options):
    folder = raw_dir / str(round_no)
    folder.mkdir(parents=True)
    make_answer_pdf(folder / "answer.pdf", round_no, **options)
    return folder / "answer.pdf"


def statuses(report):
    return {r["round"]: r["status"] for r in report["rounds"]}


def db_state(conn):
    rows = conn.execute("SELECT id, question, unit FROM questions ORDER BY id").fetchall()
    return [tuple(r) for r in rows], conn.execute("SELECT COUNT(*) FROM theory_fts").fetchone()[0]


# ---- 합성 원본으로 동기화 규칙 확인 ----
def test_sync_converts_new_round_and_rejects_bad_one(tmp_path):
    raw, bank = tmp_path / "raw", tmp_path / "bank"
    raw_round(raw, 801)
    raw_round(raw, 802, questions=14)                       # 15문항이 아니라 거부돼야 한다
    (raw / "notes").mkdir()                                 # 숫자가 아닌 폴더는 무시
    (raw / "803").mkdir()                                   # 답안 파일 없는 폴더도 무시
    conn = connect(tmp_path / "t.db")
    report = sync_raw(conn, raw, bank)
    assert statuses(report) == {801: CONVERTED, 802: FAILED}
    assert (bank / "801.json").is_file() and not (bank / "802.json").exists()
    assert report["loaded"] == 15
    assert conn.execute("SELECT COUNT(DISTINCT round) FROM questions").fetchone()[0] == 1
    text = "\n".join(format_report(report))
    assert "[실패] 802회 적재 안 함" in text and "14개" in text and "[변환] 801회" in text


def test_sync_is_idempotent_and_skips_unchanged(tmp_path):
    raw, bank = tmp_path / "raw", tmp_path / "bank"
    raw_round(raw, 801)
    conn = connect(tmp_path / "t.db")
    sync_raw(conn, raw, bank)
    first_state, first_json = db_state(conn), (bank / "801.json").read_text(encoding="utf-8")
    mtime = (bank / "801.json").stat().st_mtime
    for _ in range(2):
        report = sync_raw(conn, raw, bank)
        assert statuses(report) == {801: UP_TO_DATE}
    assert db_state(conn) == first_state and first_state[1] == 15       # 색인도 문항 수와 같다
    assert (bank / "801.json").stat().st_mtime == mtime                 # 다시 변환하지 않았다
    assert (bank / "801.json").read_text(encoding="utf-8") == first_json


def test_newer_raw_file_triggers_reconversion(tmp_path):
    raw, bank = tmp_path / "raw", tmp_path / "bank"
    answer = raw_round(raw, 801)
    conn = connect(tmp_path / "t.db")
    sync_raw(conn, raw, bank)
    make_answer_pdf(answer, 801, answers=["2"] * 15)        # 원본을 고쳐 쓴다
    future = (bank / "801.json").stat().st_mtime + 10
    os.utime(answer, (future, future))
    assert statuses(sync_raw(conn, raw, bank)) == {801: CONVERTED}
    assert json.loads((bank / "801.json").read_text(encoding="utf-8"))["theory"][0]["answer"] == "2"


def test_bad_update_keeps_previous_bank_file(tmp_path):
    raw, bank = tmp_path / "raw", tmp_path / "bank"
    answer = raw_round(raw, 801)
    conn = connect(tmp_path / "t.db")
    sync_raw(conn, raw, bank)
    before = (bank / "801.json").read_text(encoding="utf-8")
    make_answer_pdf(answer, 801, questions=14)
    future = (bank / "801.json").stat().st_mtime + 10
    os.utime(answer, (future, future))
    report = sync_raw(conn, raw, bank)
    assert statuses(report) == {801: FAILED}
    assert (bank / "801.json").read_text(encoding="utf-8") == before and report["loaded"] == 15


def test_round_number_comes_only_from_folder_name(tmp_path):
    raw_round(tmp_path / "raw", 4242)
    assert [r for r, _ in list_raw_rounds(tmp_path / "raw")] == [4242]
    assert list_raw_rounds(tmp_path / "없는폴더") == []


def test_unreadable_file_is_reported_not_raised(tmp_path):
    raw, bank = tmp_path / "raw", tmp_path / "bank"
    (raw / "805").mkdir(parents=True)
    (raw / "805" / "answer.pdf").write_bytes(b"not a pdf")
    conn = connect(tmp_path / "t.db")
    report = sync_raw(conn, raw, bank)
    assert statuses(report) == {805: FAILED} and "읽지 못했습니다" in report["rounds"][0]["problems"][0]


def test_hwp_html_collector_keeps_table_cells_and_paragraphs():
    parser = _HtmlLines()
    parser.feed("<body><p>A형</p><table><tr><td><p>④</p></td><td><p>①,③</p></td></tr></table><p>1. 질문</p></body>")
    assert parser.finish() == ["A형", "④", "①,③", "1. 질문"]


# ---- 실제 128회 원본으로 확인 (data/raw/128 과 data/bank/128.json 이 있어야 한다) ----
def test_real_128_conversion_matches_existing_bank_content(tmp_path):
    answer = REAL_RAW / "128" / "answer.pdf"
    assert answer.is_file(), "data/raw/128/answer.pdf 가 없습니다(이전 프로젝트에서 복사해 두어야 함)"
    shutil.copytree(REAL_RAW / "128", tmp_path / "raw" / "128")
    conn = connect(tmp_path / "t.db")
    assert statuses(sync_raw(conn, tmp_path / "raw", tmp_path / "bank")) == {128: CONVERTED}
    new = json.loads((tmp_path / "bank" / "128.json").read_text(encoding="utf-8"))["theory"]
    old = json.loads((BANK_DIR / "128.json").read_text(encoding="utf-8"))["theory"]
    assert len(new) == len(old) == 15
    for a, b in zip(new, old):
        assert a["number"] == b["number"]
        assert all(a[f] == b[f] for f in CONTENT_FIELDS), f"{a['number']}번 내용이 다릅니다"


def test_removed_round_returns_to_latest_ten_after_sync(tmp_path):
    answer = REAL_RAW / "128" / "answer.pdf"
    assert answer.is_file(), "data/raw/128/answer.pdf 가 없습니다"
    shutil.copytree(REAL_RAW / "128", tmp_path / "raw" / "128")
    bank = tmp_path / "bank"
    bank.mkdir()
    for path in BANK_DIR.glob("*.json"):                       # 128회 JSON 만 빼고 복사
        if path.stem != "128":
            shutil.copy(path, bank / path.name)
    conn = connect(tmp_path / "t.db")
    load_bank(conn, read_bank_files(bank))                      # 128회가 없는 DB
    query = "간이지급명세서에 대한 설명으로 옳지 않은 것"
    assert 128 not in scope_rounds(conn, 10) and scope_rounds(conn, 1) == [127]
    assert "128-11" not in [r["id"] for r in search_theory(query, conn)["results"]]
    before_rows = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]

    report = sync_raw(conn, tmp_path / "raw", bank)
    assert statuses(report) == {128: CONVERTED}
    assert scope_rounds(conn, 10)[0] == 128 and len(scope_rounds(conn, 10)) == 10
    assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == before_rows + 15
    assert "128-11" in [r["id"] for r in search_theory(query, conn)["results"]]
    assert sync_raw(conn, tmp_path / "raw", bank)["loaded"] == before_rows + 15   # 다시 돌려도 같다
