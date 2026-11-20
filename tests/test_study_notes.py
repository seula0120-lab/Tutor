"""공부 노트(data/study/재무회계·원가회계/*.json) 점검: 모양, 용어·출처 연결, 숫자 근거, 같은 단원 함정 문장과 같은 말을 하지 않는지.
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

SUBJECTS = {"재무회계": 12, "원가회계": 7, "세무회계": 15}      # 과목 → DB 단원 수
MIN_QUESTIONS_FOR_TERM = 2      # 문제 글에 이만큼(문항 수) 나온 용어만 '많이 나온 핵심 용어'로 센다
TOP_TERMS = 8
REQUIRED_TERMS = 6
TRAP_SIMILARITY = 0.7           # 개념 문장이 함정 문장과 이만큼 비슷하고, 맞는 문장보다 더 비슷하면 '함정과 같은 말'로 본다


@pytest.fixture(scope="module")
def db():
    conn = connect()
    yield conn
    conn.close()


def units(conn):
    """[(과목, 단원)] — 노트를 쓰는 과목(SUBJECTS)의 DB 단원 전부."""
    return [(s, u) for s, t, u in study.unit_rows(conn) if s in SUBJECTS]


def pieces(text):
    """한 줄을 문장 단위로 쪼갠다(한 줄에 문장이 둘이면 각각 검사)."""
    return [p.strip() for p in re.split(r"(?<=[다요])\.\s+", text) if p.strip()]


def round_of(qid):
    return int(qid.split("-")[0])


def latest_start(conn):
    """최근 10회의 첫 회차(DB 가장 최근 회차에서 아래로 10개)."""
    return conn.execute("SELECT MAX(round) FROM questions").fetchone()[0] - study.LATEST_ROUNDS + 1


def question_text(conn, qid):
    row = conn.execute("SELECT question, choices, explanation FROM questions WHERE id = ?", (qid,)).fetchone()
    return None if row is None else (row["question"] + " " + row["choices"] + " " + row["explanation"]).replace(",", "")


def test_every_unit_has_a_note_file(db):
    for subject, count in SUBJECTS.items():
        names = [u for s, u in units(db) if s == subject]
        assert len(names) == count, (subject, names)
        missing = [u for u in names if study.load_note(subject, u) is None]
        assert not missing, missing
        extra = {p.stem for p in (study.STUDY_DIR / subject).rglob("*.json")} - set(names)
        assert not extra, f"DB 에 없는 단원 파일: {extra}"


def test_note_shape_and_limits(db):
    glossary = {e["term"] for e in load_glossary()}
    for subject, unit in units(db):
        note = study.load_note(subject, unit)
        assert note["unit"] == unit and note["subject"] == subject, unit
        lines = note["concept"]["lines"]
        assert 5 <= len(lines) <= 8, (unit, len(lines))
        terms = note["concept"]["terms"]
        assert 3 <= len(terms) <= 6 and set(terms) <= glossary, (unit, [t for t in terms if t not in glossary])
        assert 2 <= len(note["practice"]) <= 3, unit
        if subject == "세무회계":
            assert all(set(c) == {"what", "how", "when", "page", "quote", "keywords"} and isinstance(c["page"], int) and 1 <= c["page"] <= 184 for c in note["changes"]), unit
            assert note["tax"] == next(t for s2, t, u in study.unit_rows(db) if u == unit), f"{unit}: 세목 폴더 값이 DB와 다름"
        else:
            assert note["changes"] == [], "재무회계·원가회계는 '2022년 이후 바뀐 것' 칸을 비워 둔다"


def test_calculation_units_have_formula_and_example(db):
    for subject, unit in units(db):
        note = study.load_note(subject, unit)
        calc = db.execute("SELECT COUNT(*) FROM questions WHERE subject=? AND unit=?", (subject, unit)).fetchone()[0]
        formula = note.get("formula")
        if formula is None:
            assert subject != "원가회계", f"{unit}: 원가 단원은 계산 공식 칸이 반드시 있어야 한다"
            continue
        assert formula["formulas"] and formula["steps"], unit
        if "pitfalls" in formula or subject == "원가회계":
            assert 1 <= len(formula["pitfalls"]) <= 2, f"{unit}: 자주 틀리는 지점은 1~2개"
        example = db.execute("SELECT unit FROM questions WHERE id = ?", (formula["example_id"],)).fetchone()
        assert example and example["unit"] == unit, f"{unit}: 대표 기출 {formula['example_id']} 이 이 단원 문항이 아님"
        assert calc


def test_numbers_come_from_cited_questions(db):
    """숫자가 들어간 개념 문장은 출처를 달고, 그 숫자가 출처 문항(문제·보기·해설)에 실제로 나와야 한다. 실무·공식 칸에는 숫자를 쓰지 않는다."""
    for subject, unit in units(db):
        note = study.load_note(subject, unit)
        for line in note["concept"]["lines"]:
            for qid in line["sources"]:
                assert question_text(db, qid) is not None, f"{unit}: 없는 출처 {qid}"
            pdf_quote = (line.get("pdf") or {}).get("quote", "")
            for number in re.findall(r"\d+", line["text"]):
                if number in pdf_quote:                      # 2025 개정세법 PDF 쪽수·인용을 단 숫자
                    continue
                assert line["sources"], f"{unit}: 숫자 {number} 에 출처가 없음: {line['text']}"
                pool = line["sources"] if subject != "세무회계" else [q for q in line["sources"] if round_of(q) >= latest_start(db)]
                assert any(number in re.sub(r"[,]", "", question_text(db, q)) for q in pool), \
                    f"{unit}: 숫자 {number} 가 출처 {line['sources']} 에 없음" + (" (세무회계 숫자는 최근 10회 문항에서만)" if subject == "세무회계" else "")
        formula = note.get("formula") or {}
        free_text = note["practice"] + formula.get("formulas", []) + formula.get("steps", []) + formula.get("pitfalls", [])
        assert not [t for t in free_text if set(re.findall(r"\d+", t)) - {"1"}], f"{unit}: 실무·공식 칸에 숫자가 있음(식 속의 '1 −' 만 허용)"


def test_concept_lines_do_not_say_the_same_as_trap_sentences(db):
    """개념 정리의 각 문장이 같은 단원 '함정'(틀린 문장으로 출제된 내용)과 매우 비슷하면 실패한다."""
    problems = []
    for subject, unit in units(db):
        rows = db.execute("SELECT * FROM questions WHERE subject=? AND unit=?", (subject, unit)).fetchall()
        right, traps, _ = collect_sentences(rows)
        note = study.load_note(subject, unit)
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
    rows = db.execute("SELECT * FROM questions WHERE subject=? AND unit=?", ("재무회계", "회계변경·오류수정")).fetchall()
    _, traps, _ = collect_sentences(rows)
    copied = traps[0][0]
    key = normalize(copied)
    ratio = max(SequenceMatcher(None, key, normalize(t[0])).ratio() for t in traps)
    assert ratio >= TRAP_SIMILARITY


def compact(text):
    return re.sub(r"\s+", "", text)


def top_terms(conn, subject, unit):
    """이 단원 기출 문제 글에 많이 나온 핵심 용어 상위 TOP_TERMS 개: 용어 사전의 용어에서 불용어(summary.STOPWORDS)를 빼고,
    문제 글에 MIN_QUESTIONS_FOR_TERM 문항 이상 나온 것만 문항 수 많은 순(같으면 가나다순)으로 센다."""
    from tutor.summary import STOPWORDS
    texts = [compact(r["question"]) for r in conn.execute("SELECT question FROM questions WHERE subject=? AND unit=?", (subject, unit))]
    counts = {}
    for entry in load_glossary():
        term = entry["term"]
        if normalize(term) in STOPWORDS:
            continue
        hits = sum(compact(term) in text for text in texts)
        if hits >= MIN_QUESTIONS_FOR_TERM:
            counts[term] = hits
    return sorted(counts, key=lambda t: (-counts[t], t))[:TOP_TERMS]


def missing_terms(note, top):
    """노트 개념 정리 줄 글에 나오지 않은 핵심 용어."""
    body = compact(" ".join(line["text"] for line in note["concept"]["lines"]))
    return [t for t in top if compact(t) not in body]


def test_concept_covers_most_frequent_terms_of_the_unit(db):
    """빠짐 검사: 단원마다 기출 문제 글에 많이 나온 핵심 용어 상위 8개 중 6개(용어가 그보다 적으면 전부) 이상이 개념 정리 줄에 나와야 한다."""
    problems = []
    for subject, unit in units(db):
        top = top_terms(db, subject, unit)
        missing = missing_terms(study.load_note(subject, unit), top)
        need = min(REQUIRED_TERMS, len(top))
        if len(top) - len(missing) < need:
            problems.append(f"{subject}/{unit}: 핵심 용어 {len(top)}개 중 {len(top) - len(missing)}개만 나옴(필요 {need}). 빠진 용어: {missing}")
    assert not problems, "\n".join(problems)


def test_coverage_check_flags_a_note_missing_the_frequent_terms(db):
    """검사 자체가 동작하는지: 자본 노트에서 이익잉여금·자기주식을 지운 글은 빠짐으로 걸린다."""
    top = top_terms(db, "재무회계", "자본")
    assert len(top) >= REQUIRED_TERMS and "이익잉여금" in top and "자기주식" in top
    note = study.load_note("재무회계", "자본")
    assert missing_terms(note, top) == [t for t in top if t not in "".join(l["text"] for l in note["concept"]["lines"])]
    stripped = {"concept": {"lines": [{"text": l["text"].replace("이익잉여금", "").replace("자기주식", "")} for l in note["concept"]["lines"]]}}
    assert {"이익잉여금", "자기주식"} <= set(missing_terms(stripped, top))


def test_capital_formula_subtracts_capital_reduction(db):
    formulas = study.load_note("재무회계", "자본")["formula"]["formulas"]
    assert any("기말자본금" in f and "− 감자(액면 기준)" in f for f in formulas)


def test_fixed_asset_note_covers_depreciation_methods_revaluation_impairment_exchange_and_capex(db):
    body = compact(" ".join(l["text"] for l in study.load_note("재무회계", "유형자산")["concept"]["lines"]))
    for needed in ["정액법", "정률법", "연수합계법", "생산량비례법", "재평가잉여금", "재평가손실", "손상차손환입", "동종", "이종", "자본적지출", "수익적지출"]:
        assert needed in body, needed


def test_cost_notes_reach_the_page_with_pitfalls_and_example(db):
    """화면이 읽는 study.get_note 결과에 원가 노트의 풀이 순서·자주 틀리는 지점·대표 기출(정답 없이)이 들어 있다."""
    for subject, unit in units(db):
        if subject != "원가회계":
            continue
        out = study.get_note(db, unit)
        formula = out["note"]["formula"]
        assert formula["steps"] and 1 <= len(formula["pitfalls"]) <= 2, unit
        assert formula["example"]["id"] == formula["example_id"] and "answer" not in formula["example"], unit
        assert out["drafts"] == ["concept", "practice", "formula"], unit
        assert any("확인 필요" in t for t in out["note"]["practice"]), unit


def test_cost_concept_note_states_the_no_ending_inventory_condition(db):
    """112-9 는 '기말재고자산은 없다고 가정'한 문제다. 노트가 그 조건 없이 '이익은 변하지 않는다'고 하면 안 된다."""
    line = next(l["text"] for l in study.load_note("원가회계", "원가개념·분류")["concept"]["lines"] if "광고선전비" in l["text"])
    assert "기말재고가 없다고 가정할 때" in line and "기말재고가 남으면" in line and "재고자산에 포함" in line
    assert "112-9" in next(l["sources"] for l in study.load_note("원가회계", "원가개념·분류")["concept"]["lines"] if "광고선전비" in l["text"])


# ------------------------------------------------------------------ 세무회계 노트: 최신 10회 우선·숫자 출처·옛 기출과 다름 표시·실무 메뉴 이름
TAX = "세무회계"
CHECK = "최신 법령 확인 필요"
KCLEP_KNOWN = ("매입매출전표입력", "부가가치세신고서", "원천징수이행상황신고서", "일반전표입력", "고정자산등록", "연말정산", "소득금액조정합계표", "조정명세서", "세무조정", "과세표준 및 세액조정계산서")


def tax_notes(db):
    return [(unit, study.load_note(TAX, unit)) for s, t, unit in study.unit_rows(db) if s == TAX]


def test_tax_concept_lines_follow_latest_rounds_or_say_they_need_checking(db):
    """세무 개념 줄은 최근 10회 기출 문항을 출처로 달았거나, 그렇지 못하면 '최신 법령 확인 필요'(또는 2025 개정세법 쪽수 인용)를 단다."""
    start = latest_start(db)
    problems = []
    for unit, note in tax_notes(db):
        for line in note["concept"]["lines"]:
            if line.get("pdf"):
                assert line["pdf"]["page"] >= 1 and line["pdf"]["quote"], unit
                continue
            recent = [q for q in line["sources"] if round_of(q) >= start]
            if not recent and CHECK not in line.get("check", ""):
                problems.append(f"{unit}: 최근 10회 출처도 '{CHECK}' 표시도 없음: {line['text'][:30]}")
    assert not problems, "\n".join(problems)


def test_tax_old_vs_new_marks_cite_both_rounds(db):
    """'옛 기출과 다름(○○회 vs ○○회)' 표시는 두 회차의 문항을 모두 출처로 달고 있어야 하며, 숫자는 본문에 쓰지 않았어도 표시 자체는 있다."""
    marks = 0
    for unit, note in tax_notes(db):
        for line in note["concept"]["lines"]:
            if "diff" not in line:
                continue
            marks += 1
            m = re.fullmatch(r"옛 기출과 다름\((\d+)회 vs (\d+)회\)", line["diff"])
            assert m, f"{unit}: 표시 형식 오류 {line['diff']}"
            old, new = int(m.group(1)), int(m.group(2))
            rounds = {round_of(q) for q in line["sources"]}
            assert old < new and {old, new} <= rounds, f"{unit}: 표시한 두 회차가 출처에 없음 {line['diff']} / {line['sources']}"
    assert marks >= 5


def test_tax_practice_lines_use_known_menu_names_or_say_confirm(db):
    for unit, note in tax_notes(db):
        for text in note["practice"]:
            assert "확인 필요" in text or any(name in text for name in KCLEP_KNOWN), f"{unit}: 확신 없는 메뉴 이름을 '확인 필요' 없이 씀: {text[:30]}"
        assert any("확인 필요" in t for t in note["practice"]), unit


def test_tax_notes_list_pdf_cited_revisions_and_reach_the_page(db):
    """get_note 가 ⑥ 항목(쪽수 포함), 자료 없는 해 안내, 연결된 tax_changes 메모를 준다. 재무·원가 노트는 비어 있다."""
    out = study.get_note(db, "세금계산서")
    assert out["tax"] == "부가가치세" and out["note"]["change_gap"] == "2023·2024·2026 개정 자료 없음 — 확인 필요"
    assert out["note"]["changes"][0]["page"] == 27 and out["note"]["change_memos"] == []
    finance = study.get_note(db, "재고자산")["note"]
    assert finance["changes"] == [] and finance["change_gap"] == "" and finance["change_memos"] == []


def test_tax_change_memos_link_by_tax_and_unit_or_keyword(db, monkeypatch):
    memos = [{"keyword": "가산세", "memo": "A", "year": 2024},                        # 세목 없음 → 키워드가 단원 글에 있으면 어디서나
             {"keyword": "아무말", "memo": "B", "tax": "부가가치세", "unit": "세금계산서"},  # 단원을 적으면 그 단원에만
             {"keyword": "가산세", "memo": "C", "tax": "소득세"},                      # 다른 세목
             {"keyword": "zzz없는말", "memo": "D"}]
    monkeypatch.setattr(study, "tax_changes", lambda: memos)
    assert [m["memo"] for m in study.get_note(db, "세금계산서")["note"]["change_memos"]] == ["A", "B"]
    assert [m["memo"] for m in study.get_note(db, "원천징수·지급명세서")["note"]["change_memos"]] == ["A", "C"]
    assert study.get_note(db, "영세율·면세")["note"]["change_memos"] == []
    overview = study.changes_overview(db)
    assert [m["memo"] for m in overview["loose_memos"]] == ["D"]


def test_changes_overview_collects_only_tax_sections_with_pages(db):
    overview = study.changes_overview(db)
    assert [g["tax"] for g in overview["taxes"]] == ["법인세", "부가가치세", "소득세"]
    assert sum(len(g["units"]) for g in overview["taxes"]) == 15
    items = [c for g in overview["taxes"] for u in g["units"] for c in u["items"]]
    assert len(items) >= 25 and all(c["page"] for c in items)
    assert overview["gap"].startswith("2023·2024·2026") and "PDF 쪽수" in overview["source"]
