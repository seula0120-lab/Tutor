import random

from conftest import item
from tutor import mock, records
from tutor.bank import load_bank
from tutor.db import connect
from tutor.web import dispatch

C4 = ["첫째 문장이다.", "둘째 문장이다.", "셋째 문장이다.", "넷째 문장이다."]
STEMS = {1: "재고자산", 6: "보조부문원가", 11: "부가가치세법상", 13: "소득세법상", 14: "법인세법상"}


def full_round(round_no):
    """한 회차 15문항: 1~5 재무, 6~10 원가, 11~12 부가세, 13 소득세, 14~15 법인세. 정답은 모두 2번."""
    def stem(n):
        key = max(k for k in STEMS if k <= n) if n >= 1 else 1
        return f"다음 중 {STEMS[key]} 문항{n}에 대한 설명으로 옳은 것은?"
    return [item(n, stem(n), C4, "2", f"{n}번 해설") for n in range(1, 16)]


def bank(tmp_path, rounds=4):
    conn = connect(tmp_path / "mock.db")
    load_bank(conn, [(r, full_round(r)) for r in range(1, rounds + 1)])
    return conn


def counts(conn, questions):
    ids = [q["id"] for q in questions]
    rows = [conn.execute("SELECT subject, tax FROM questions WHERE id = ?", (i,)).fetchone() for i in ids]
    subjects = {}
    for r in rows:
        subjects[r["subject"]] = subjects.get(r["subject"], 0) + 1
    taxes = {r["tax"]: 0 for r in rows if r["subject"] == "세무회계"}
    for r in rows:
        if r["subject"] == "세무회계":
            taxes[r["tax"]] += 1
    return subjects, taxes


def test_exam_has_five_per_subject_without_duplicates_or_answers(tmp_path):
    conn = bank(tmp_path)
    for seed in range(20):
        exam = mock.pick_exam(conn, random.Random(seed))
        subjects, taxes = counts(conn, exam)
        assert subjects == {"재무회계": 5, "원가회계": 5, "세무회계": 5}
        assert len({q["id"] for q in exam}) == 15
        assert sorted(taxes.values()) == [1, 2, 2] and set(taxes) == {"부가가치세", "소득세", "법인세"}   # 세목을 섞음
        assert all("answer" not in q and "explanation" not in q for q in exam)


def test_exam_order_is_subject_blocks(tmp_path):
    conn = bank(tmp_path)
    exam = mock.pick_exam(conn, random.Random(1))
    assert [q["subject"] for q in exam] == ["재무회계"] * 5 + ["원가회계"] * 5 + ["세무회계"] * 5


def test_already_correct_questions_are_pushed_back(tmp_path):
    conn = bank(tmp_path, rounds=2)            # 재무 10문항 중 6개를 맞힌 상태
    solved = [f"{r}-{n}" for r in (1, 2) for n in (1, 2, 3)]
    for qid in solved:
        records.save(conn, qid, "2", True)
    unsolved = {f"{r}-{n}" for r in (1, 2) for n in (4, 5)}
    for seed in range(15):
        finance = {q["id"] for q in mock.pick_exam(conn, random.Random(seed)) if q["subject"] == "재무회계"}
        assert unsolved <= finance                              # 못 맞힌 4개는 항상 들어간다
        assert len(finance & set(solved)) == 1                  # 모자란 1개만 맞힌 문항으로 채운다


def test_shortage_falls_back_to_other_tax_questions(tmp_path):
    conn = connect(tmp_path / "s.db")
    items = [x for x in full_round(1) if x["number"] not in (13,)]       # 소득세 문항이 없는 은행
    load_bank(conn, [(1, items), (2, full_round(2)[:13])])
    exam = mock.pick_exam(conn, random.Random(0))
    assert len(exam) == 15 and len({q["id"] for q in exam}) == 15


def test_grading_scores_two_points_each_with_subject_breakdown(tmp_path):
    conn = bank(tmp_path)
    exam = mock.pick_exam(conn, random.Random(3))
    ids = [q["id"] for q in exam]
    answers = {i: "2" for i in ids}                 # 전부 정답
    result = mock.grade(conn, ids, answers, now=1000.0)
    assert result["score"] == 30 and result["max_score"] == 30 and result["wrong"] == []
    assert result["by_subject"]["세무회계"] == {"score": 10, "max": 10}
    # 3개 틀림(재무 1·원가 1·세무 1) + 1개 미응답(세무)
    answers[ids[0]] = "4"
    answers[ids[5]] = "1"
    answers[ids[10]] = "3"
    del answers[ids[11]]
    result = mock.grade(conn, ids, answers, now=2000.0)
    assert result["score"] == 22 and len(result["wrong"]) == 4
    assert result["by_subject"] == {"재무회계": {"score": 8, "max": 10}, "원가회계": {"score": 8, "max": 10},
                                    "세무회계": {"score": 6, "max": 10}}
    assert {w["id"] for w in result["wrong"]} == {ids[0], ids[5], ids[10], ids[11]}
    assert all(w["explanation"] and w["answer"] == "2" for w in result["wrong"])       # 틀린 문항만 해설을 돌려준다


def test_multi_answer_question_accepts_any_listed_choice(tmp_path):
    conn = connect(tmp_path / "m.db")
    load_bank(conn, [(1, [item(1, "다음 중 재고자산 설명으로 옳은 것은?", C4, "1,3", "해설")])])
    assert mock.grade(conn, ["1-1"], {"1-1": "3"})["score"] == 2


def test_grade_rejects_bad_ids_and_leaves_no_trace(tmp_path):
    conn = bank(tmp_path, rounds=1)
    import pytest
    for ids in ([], ["1-1", "1-1"]):
        with pytest.raises(ValueError):
            mock.grade(conn, ids, {})
    with pytest.raises(ValueError):
        mock.grade(conn, ["1-1", "99-9"], {})
    assert conn.execute("SELECT COUNT(*) FROM mock_results").fetchone()[0] == 0


def test_submission_writes_records_and_history_trend(tmp_path):
    conn = bank(tmp_path)
    ids = [q["id"] for q in mock.pick_exam(conn, random.Random(0))]
    mock.grade(conn, ids, {i: "2" for i in ids[:10]} | {i: "1" for i in ids[10:]}, now=1000.0)   # 20점
    result = mock.grade(conn, ids, {i: "2" for i in ids}, now=5000.0)                           # 30점
    assert [(h["n"], h["score"], h["diff"]) for h in result["history"]] == [(1, 20, None), (2, 30, 10)]
    src = {r[0] for r in conn.execute("SELECT DISTINCT source FROM records")}
    assert src == {"mock"} and conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 30
    assert len(records.notebook(conn)) == 0                    # 두 번째 시험에서 모두 맞혀 오답노트가 비었다


def test_mock_api_flow(tmp_path):
    conn = bank(tmp_path)
    status, new = dispatch("GET", "/api/mock/new", {}, {}, conn)
    assert status == 200 and len(new["questions"]) == 15
    ids = [q["id"] for q in new["questions"]]
    status, result = dispatch("POST", "/api/mock/submit", {}, {"ids": ids, "answers": {ids[0]: "2"}}, conn)
    assert status == 200 and result["score"] == 2 and len(result["wrong"]) == 14
    assert dispatch("POST", "/api/mock/submit", {}, {"ids": []}, conn)[0] == 400
    assert dispatch("GET", "/api/mock/history", {}, {}, conn)[1]["history"][0]["score"] == 2
    small = connect(tmp_path / "small.db")
    assert dispatch("GET", "/api/mock/new", {}, {}, small)[0] == 404


def test_true_duplicate_pairs_never_share_one_exam(tmp_path, monkeypatch):
    conn = bank(tmp_path, rounds=2)                     # 과목당 후보가 적어 중복쌍이 함께 뽑히기 쉽다
    pairs = (("1-1", "2-1"), ("1-6", "2-6"), ("1-12", "2-12"))
    both = lambda exam: any({a, b} <= {q["id"] for q in exam} for a, b in pairs)
    assert any(both(mock.pick_exam(conn, random.Random(s))) for s in range(200))      # 막지 않으면 함께 나온다(시험이 유효함)
    monkeypatch.setattr(mock, "PARTNER", {a: b for a, b in pairs} | {b: a for a, b in pairs})
    for seed in range(200):
        exam = mock.pick_exam(conn, random.Random(seed))
        assert not both(exam) and len(exam) == 15


def test_real_duplicate_pairs_are_the_three_reviewed_in_data_cleanup():
    from pathlib import Path
    doc = (Path(__file__).resolve().parent.parent / "docs" / "data_cleanup.md").read_text(encoding="utf-8")
    assert len(mock.DUPLICATE_PAIRS) == 3
    for a, b in mock.DUPLICATE_PAIRS:
        assert f"{a} ~ {b}" in doc and "**같은 문제**" in doc.split(f"{a} ~ {b}")[1].split("\n")[0]
