import random

from tutor import quiz, records
from tutor.analysis import MIN_SOLVED, study_order
from tutor.bank import load_bank
from tutor.db import connect
from tutor.web import dispatch
from test_mock import full_round


def bank(tmp_path, rounds=8):
    conn = connect(tmp_path / "st.db")
    load_bank(conn, [(r, full_round(r)) for r in range(1, rounds + 1)])
    return conn


def unit_row(order, unit):
    return next(r for r in order["rows"] if r["unit"] == unit)


def solve(conn, ids, correct_flags):
    for qid, ok in zip(ids, correct_flags):
        records.save(conn, qid, "2" if ok else "1", ok)


def test_expected_loss_formula(tmp_path):
    conn = bank(tmp_path)
    # 재고자산(재무 1~5번)에서 서로 다른 문항 6개: 4개 정답·2개 오답 → 정답률 4/6
    ids = [f"{r}-{n}" for r in (1, 2) for n in (1, 2, 3)]
    solve(conn, ids, [True, True, True, True, False, False])
    order = study_order(conn)
    unit = conn.execute("SELECT unit FROM questions WHERE id = '1-1'").fetchone()["unit"]
    row = unit_row(order, unit)
    assert row["solved_questions"] == 6 and row["accuracy"] == round(4 / 6, 3)
    assert row["expected_loss"] == round(row["points_per_round"] * (1 - 4 / 6), 2)
    assert row["status"] == "ok"


def test_unit_with_fewer_than_five_solved_is_insufficient_not_invented(tmp_path):
    conn = bank(tmp_path)
    solve(conn, ["1-6", "2-6", "3-6", "4-6"], [False] * 4)               # 4문항 전부 오답이어도 정답률을 만들지 않는다
    row = unit_row(study_order(conn), conn.execute("SELECT unit FROM questions WHERE id='1-6'").fetchone()["unit"])
    assert MIN_SOLVED == 5 and row["status"] == "기록 부족"
    assert row["accuracy"] is None and row["expected_loss"] is None and row["solved_questions"] == 4


def test_no_records_means_every_unit_insufficient(tmp_path):
    order = study_order(bank(tmp_path))
    assert order["rows"] and all(r["status"] == "기록 부족" and r["accuracy"] is None for r in order["rows"])


def test_ordering_is_by_loss_with_insufficient_last(tmp_path):
    conn = bank(tmp_path)
    finance = [f"{r}-{n}" for r in range(1, 6) for n in (1,)]           # 재무 단원: 5문항 오답 → 정답률 0
    solve(conn, finance, [False] * 5)
    cost = [f"{r}-6" for r in range(1, 6)]                               # 원가 단원: 5문항 정답 → 정답률 100%
    solve(conn, cost, [True] * 5)
    rows = study_order(conn)["rows"]
    labels = [r["status"] for r in rows]
    assert labels[:2] == ["ok", "ok"] and set(labels[2:]) == {"기록 부족"}
    assert rows[0]["expected_loss"] > rows[1]["expected_loss"] == 0.0
    assert rows[0]["subject"] == "재무회계"


def test_seen_only_records_do_not_count_as_solved(tmp_path):
    conn = bank(tmp_path)
    for r in range(1, 8):
        records.save(conn, f"{r}-1", "", None, seen_only=True)
    assert all(r["solved_questions"] == 0 for r in study_order(conn)["rows"])


def test_pick_set_prefers_unsolved_and_is_unique(tmp_path):
    conn = bank(tmp_path)
    unit = conn.execute("SELECT unit FROM questions WHERE id='1-1'").fetchone()["unit"]
    all_ids = [r["id"] for r in conn.execute("SELECT id FROM questions WHERE unit = ?", (unit,))]
    done = all_ids[:len(all_ids) - 5]
    for qid in done:
        records.save(conn, qid, "2", True)
    picked = quiz.pick_set(conn, unit=unit, count=5, rng=random.Random(0))
    assert len(picked) == 5 == len(set(picked)) and not set(picked) & set(done)


def test_study_apis(tmp_path):
    conn = bank(tmp_path)
    status, order = dispatch("GET", "/api/study_order", {"scope": "all"}, {}, conn)
    assert status == 200 and order["min_solved"] == 5
    row = order["rows"][0]
    status, got = dispatch("GET", "/api/quiz_set", {"subject": row["subject"], "tax": row["tax"], "unit": row["unit"]}, {}, conn)
    assert status == 200 and 1 <= len(got["ids"]) <= 5
    assert dispatch("GET", "/api/quiz_set", {"unit": "없는단원"}, {}, conn)[0] == 404
