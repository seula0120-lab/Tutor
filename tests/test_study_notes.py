"""공부 노트(data/study/재무회계/*.json) 점검: 모양, 용어·출처 연결, 숫자 근거, 같은 단원 함정 문장과 같은 말을 하지 않는지.
진짜 기출 DB(data/tutor.db)를 읽는다(다른 데이터 테스트와 같다)."""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

import pytest

from tutor import study
from tutor.db import connect
from tutor.glossary import load_glossary
from tutor.summary import collect_sentences, normalize

SUBJECT = "재무회계"
TRAP_SIMILARITY = 0.7           # 개념 문장이 함정 문장과 이만큼 비슷하고, 맞는 문장보다 더 비슷하면 '함정과 같은 말'로 본다


@pytest.fixture(scope="module")
def db():
    conn = connect()
    yield conn
    conn.close()


def units(conn):
    return [u for s, t, u in study.unit_rows(conn) if s == SUBJECT]


def pieces(text):
    """한 줄을 문장 단위로 쪼갠다(한 줄에 문장이 둘이면 각각 검사)."""
    return [p.strip() for p in re.split(r"(?<=[다요])\.\s+", text) if p.strip()]


def question_text(conn, qid):
    row = conn.execute("SELECT question, choices, explanation FROM questions WHERE id = ?", (qid,)).fetchone()
    return None if row is None else (row["question"] + " " + row["choices"] + " " + row["explanation"]).replace(",", "")


def test_every_financial_unit_has_a_note_file(db):
    names = units(db)
    assert len(names) == 12
    missing = [u for u in names if study.load_note(SUBJECT, u) is None]
    assert not missing, missing
    extra = {p.stem for p in (study.STUDY_DIR / SUBJECT).glob("*.json")} - set(names)
    assert not extra, f"DB 에 없는 단원 파일: {extra}"


def test_note_shape_and_limits(db):
    glossary = {e["term"] for e in load_glossary()}
    for unit in units(db):
        note = study.load_note(SUBJECT, unit)
        assert note["unit"] == unit and note["subject"] == SUBJECT, unit
        lines = note["concept"]["lines"]
        assert 5 <= len(lines) <= 8, (unit, len(lines))
        terms = note["concept"]["terms"]
        assert 3 <= len(terms) <= 6 and set(terms) <= glossary, (unit, [t for t in terms if t not in glossary])
        assert 2 <= len(note["practice"]) <= 3, unit
        assert note["changes"] == [], "재무회계는 '2022년 이후 바뀐 것' 칸을 비워 둔다"


def test_calculation_units_have_formula_and_example(db):
    for unit in units(db):
        note = study.load_note(SUBJECT, unit)
        calc = db.execute("SELECT COUNT(*) FROM questions WHERE subject=? AND unit=?", (SUBJECT, unit)).fetchone()[0]
        formula = note.get("formula")
        if formula is None:
            continue
        assert formula["formulas"] and formula["steps"], unit
        example = db.execute("SELECT unit FROM questions WHERE id = ?", (formula["example_id"],)).fetchone()
        assert example and example["unit"] == unit, f"{unit}: 대표 기출 {formula['example_id']} 이 이 단원 문항이 아님"
        assert calc


def test_numbers_come_from_cited_questions(db):
    """숫자가 들어간 개념 문장은 출처를 달고, 그 숫자가 출처 문항(문제·보기·해설)에 실제로 나와야 한다. 실무·공식 칸에는 숫자를 쓰지 않는다."""
    for unit in units(db):
        note = study.load_note(SUBJECT, unit)
        for line in note["concept"]["lines"]:
            for qid in line["sources"]:
                assert question_text(db, qid) is not None, f"{unit}: 없는 출처 {qid}"
            for number in re.findall(r"\d+", line["text"]):
                assert line["sources"], f"{unit}: 숫자 {number} 에 출처가 없음: {line['text']}"
                assert any(number in re.sub(r"[,]", "", question_text(db, q)) for q in line["sources"]), \
                    f"{unit}: 숫자 {number} 가 출처 {line['sources']} 에 없음"
        free_text = note["practice"] + ((note.get("formula") or {}).get("formulas", [])) + ((note.get("formula") or {}).get("steps", []))
        assert not [t for t in free_text if set(re.findall(r"\d+", t)) - {"1"}], f"{unit}: 실무·공식 칸에 숫자가 있음(식 속의 '1 −' 만 허용)"


def test_concept_lines_do_not_say_the_same_as_trap_sentences(db):
    """개념 정리의 각 문장이 같은 단원 '함정'(틀린 문장으로 출제된 내용)과 매우 비슷하면 실패한다."""
    problems = []
    for unit in units(db):
        rows = db.execute("SELECT * FROM questions WHERE subject=? AND unit=?", (SUBJECT, unit)).fetchall()
        right, traps, _ = collect_sentences(rows)
        note = study.load_note(SUBJECT, unit)
        for line in note["concept"]["lines"]:
            for piece in pieces(line["text"]):
                key = normalize(piece)
                trap = max(((SequenceMatcher(None, key, normalize(t[0])).ratio(), t[0]) for t in traps), default=(0.0, ""))
                good = max((SequenceMatcher(None, key, normalize(r[0])).ratio() for r in right), default=0.0)
                if trap[0] >= TRAP_SIMILARITY and trap[0] > good:
                    problems.append(f"{unit}: '{piece[:40]}' ≈ 함정 '{trap[1][:40]}' ({trap[0]:.2f} > 맞는 문장 {good:.2f})")
    assert not problems, "\n".join(problems)


def test_conflict_check_catches_a_copied_trap(db):
    """검사 자체가 동작하는지: 함정 문장을 그대로 베끼면 걸린다."""
    rows = db.execute("SELECT * FROM questions WHERE subject=? AND unit=?", (SUBJECT, "회계변경·오류수정")).fetchall()
    _, traps, _ = collect_sentences(rows)
    copied = traps[0][0]
    key = normalize(copied)
    ratio = max(SequenceMatcher(None, key, normalize(t[0])).ratio() for t in traps)
    assert ratio >= TRAP_SIMILARITY
