import json

import pytest

from tutor import records, study
from tutor.web import dispatch


@pytest.fixture
def notes_dir(tmp_path, monkeypatch):
    """임시 노트 폴더: 재고자산 노트 하나만 있다(진짜 data/study 는 건드리지 않는다)."""
    folder = tmp_path / "study" / "재무회계"
    folder.mkdir(parents=True)
    (folder / "재고자산.json").write_text(json.dumps({
        "unit": "재고자산", "subject": "재무회계",
        "concept": {"lines": [{"text": "예시 개념.", "sources": []}], "terms": ["재고자산", "없는용어"]},
        "practice": ["일반전표입력 예시."], "formula": {"formulas": ["식"], "steps": ["순서"], "example_id": "1-1"}, "changes": []}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(study, "STUDY_DIR", tmp_path / "study")
    return tmp_path / "study"


def test_curriculum_has_three_subject_cards_with_units_and_progress(conn, notes_dir):
    cards = study.curriculum(conn)
    assert [c["subject"] for c in cards] == ["재무회계", "원가회계", "세무회계"]
    assert [c["label"] for c in cards] == ["재무회계", "원가관리회계", "세무회계"]
    finance = cards[0]
    assert {u["unit"] for u in finance["units"]} == {"재고자산", "자본", "유형자산"}
    assert finance["total"] == 3 and finance["done"] == 0 and finance["progress"] == 0.0
    assert {u["unit"]: u["has_note"] for u in finance["units"]} == {"재고자산": True, "자본": False, "유형자산": False}
    assert set(cards[2]["taxes"]) == {"부가가치세", "소득세", "법인세"}


def test_progress_is_saved_and_counted(conn, notes_dir):
    study.save_progress(conn, "재고자산", "read")
    study.save_progress(conn, "자본", "understood")
    finance = study.curriculum(conn)[0]
    assert finance["done"] == 2 and finance["understood"] == 1 and finance["progress"] == round(2 / 3, 3)
    study.save_progress(conn, "재고자산", "")                       # 되돌리기
    assert study.curriculum(conn)[0]["done"] == 1
    with pytest.raises(ValueError):
        study.save_progress(conn, "재고자산", "완료")
    with pytest.raises(ValueError):
        study.save_progress(conn, "없는단원", "read")


def test_note_overview_comes_from_db_and_terms_link_to_glossary(conn, notes_dir):
    out = study.get_note(conn, "재고자산")
    assert out["overview"] == {"questions": 1, "rounds": 1, "latest_round": 1, "points_per_round": study.overview(conn, "재무회계", "", "재고자산")["points_per_round"]}
    terms = {t["term"]: t["meaning"] for t in out["note"]["concept"]["terms"]}
    assert terms["재고자산"] and terms["없는용어"] == ""            # 사전에 있는 용어는 뜻이 붙고, 없으면 빈 뜻
    assert out["note"]["formula"]["example"]["id"] == "1-1" and "answer" not in out["note"]["formula"]["example"]
    assert out["drafts"] == ["concept", "practice", "formula"]


def test_missing_note_file_gives_empty_note_but_still_has_exam_data(conn, notes_dir):
    out = study.get_note(conn, "자본")
    assert out["note"] is None and out["overview"]["questions"] == 1
    assert set(out["sentences"]) == {"right", "traps", "excluded_count"}


def test_review_badge_can_be_cleared_and_restored(conn, notes_dir):
    assert study.set_review(conn, "재고자산", "concept", True) == ["concept"]
    assert study.get_note(conn, "재고자산")["drafts"] == ["practice", "formula"]
    assert study.set_review(conn, "재고자산", "concept", False) == []
    with pytest.raises(ValueError):
        study.set_review(conn, "재고자산", "sentences", True)          # 기출 문장 칸은 AI 초안이 아니다


def test_unit_sentences_use_summary_logic_and_prefer_recent_rounds(conn):
    sentences = study.unit_sentences(conn, "재무회계", "", "재고자산")
    assert set(sentences) == {"right", "traps", "excluded_count"}
    for key in ("right", "traps"):
        rounds = [s["latest_round"] for s in sentences[key]]
        assert rounds == sorted(rounds, reverse=True)
        assert all(s["sources"] and "-" in s["sources"][0] for s in sentences[key])


def test_sentence_fragments_are_left_out_of_exam_sentences():
    assert study.is_full_sentence("자기주식은 자본조정으로 처리한다.") and study.is_full_sentence("당기순이익이 해마다 늘어난다")
    assert not study.is_full_sentence("자산의 과소계상") and not study.is_full_sentence("과대계상 과소계상 과대계상")
    assert not study.is_full_sentence("(차) 감가상각비 400,000 (대) 감가상각누계액 400,000 원 원 증가다")


def test_roadmap_orders_by_points_times_recent_rate_and_moves_wrong_units_first(conn, notes_dir):
    rows = study.roadmap(conn)
    assert {r["unit"] for r in rows} == {u for _, _, u in study.unit_rows(conn)}
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)
    assert all(r["score"] == round(r["points_per_round"] * r["recent_rate"], 3) for r in rows)
    last = rows[-1]["unit"]
    qid = conn.execute("SELECT id FROM questions WHERE unit = ?", (last,)).fetchone()["id"]
    records.save(conn, qid, "1", 0)                                     # 오답 기록
    after = study.roadmap(conn)
    assert after[0]["unit"] == last and after[0]["wrong_open"] == 1


def test_study_routes(conn, notes_dir):
    status, payload = dispatch("GET", "/api/study", {}, {}, conn)
    assert status == 200 and len(payload["cards"]) == 3 and payload["roadmap"]
    status, note = dispatch("GET", "/api/study/note", {"unit": "재고자산"}, {}, conn)
    assert status == 200 and note["note"]["practice"] == ["일반전표입력 예시."]
    assert dispatch("GET", "/api/study/note", {"unit": "없는단원"}, {}, conn)[0] == 400
    status, saved = dispatch("POST", "/api/study/progress", {}, {"unit": "재고자산", "status": "understood"}, conn)
    assert status == 200 and saved["cards"][0]["understood"] == 1
    assert dispatch("POST", "/api/study/progress", {}, {"unit": "재고자산", "status": "x"}, conn)[0] == 400
    assert dispatch("POST", "/api/study/review", {}, {"unit": "재고자산", "section": "formula", "reviewed": True}, conn)[1]["reviewed"] == ["formula"]
