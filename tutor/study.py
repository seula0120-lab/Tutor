"""'공부' 페이지: 과목·단원 목록과 진도, 단원 학습 노트, 복귀 로드맵.

노트 내용(개념 정리·실무 연결·계산 공식 등)은 data/study/<과목>/<단원>.json 에만 있고 코드에는 없다.
기출에서 오는 칸(한눈에·시험에 나온 문장)은 DB 에서 계산하고, 요약 카드와 같은 문장 모으기(summary.collect_sentences)를 쓴다.
진도(읽음·이해함)와 AI 초안 '검토 완료' 표시는 서버 DB(study_progress, study_review)에 저장한다.
"""
import json
from pathlib import Path

from . import clock
from .analysis import unit_profile
from .glossary import load_glossary
from .quiz import public_question
from .records import notebook
from .notice import tax_changes
from .search import LATEST_ROUNDS
from .summary import collect_sentences, merge_sentences

STUDY_DIR = Path(__file__).resolve().parent.parent / "data" / "study"
CARDS = (("재무회계", "재무회계"), ("원가회계", "원가관리회계"), ("세무회계", "세무회계"))   # (DB 과목 이름, 카드 이름)
STATUSES = ("", "read", "understood")                 # '' = 아직 안 봄
AI_SECTIONS = ("concept", "practice", "formula")      # AI 초안이라 사람이 '검토 완료' 로 바꿔야 하는 칸
MIN_SENTENCE_LENGTH = 12                              # 이보다 짧은 조각은 문장이 아니다
TAX_SUBJECT = "세무회계"
CHANGES_GAP = "2023·2024·2026 개정 자료 없음 — 확인 필요"     # 2025 개정세법 PDF 한 권만 있다. 다른 해 개정은 지어내지 않는다.
CHANGES_SOURCE = "2025 개정세법(한국세무사회 전체 통합본) PDF 쪽수(인쇄된 쪽 번호 = PDF 쪽수 − 16)"
SENTENCE_LIMIT = 8                                    # 시험에 나온 문장: 맞는 문장·함정 각각


def unit_rows(conn):
    """DB 의 (과목, 세목, 단원) 목록."""
    return [(r["subject"], r["tax"], r["unit"]) for r in conn.execute(
        "SELECT DISTINCT subject, tax, unit FROM questions ORDER BY subject, tax, unit")]


def find_unit(conn, unit):
    """단원 이름 → (과목, 세목, 단원). 없으면 ValueError."""
    for subject, tax, name in unit_rows(conn):
        if name == unit:
            return subject, tax, name
    raise ValueError("없는 단원입니다.")


def note_path(subject, unit, study_dir=None):
    return Path(study_dir or STUDY_DIR) / subject / f"{unit}.json"


def load_note(subject, unit, study_dir=None):
    """노트 파일을 읽는다. 세무회계는 data/study/세무회계/<세목>/<단원>.json(단원 이름은 과목 안에서 겹치지 않는다).
    파일이 없으면 None(화면에는 '노트 준비 중' 으로 보인다)."""
    base = Path(study_dir or STUDY_DIR) / subject
    for path in (note_path(subject, unit, study_dir), *sorted(base.glob(f"*/{unit}.json"))):
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def note_text(note):
    """노트 개념·바뀐 것 글을 한 덩어리로(세법 메모 연결에 쓴다)."""
    lines = [l["text"] for l in (note.get("concept") or {}).get("lines", [])]
    return " ".join(lines + [f'{c["what"]} {c["how"]}' for c in note.get("changes") or [] if isinstance(c, dict)])


def change_memos(tax, unit, note):
    """data/tax_changes.json 메모 중 이 단원에 닿는 것. 규칙: 세목이 같거나 비어 있고, (단원 이름을 적었으면 그 단원만 /
    안 적었으면 핵심어가 단원 이름이나 노트 글에 있을 때)."""
    text = note_text(note) if note else ""
    out = []
    for memo in tax_changes():
        if memo.get("tax") and memo["tax"] != tax:
            continue
        if memo.get("unit") and memo["unit"] != unit:
            continue
        if not memo.get("unit") and memo["keyword"] not in unit and memo["keyword"] not in text:
            continue
        out.append({"year": memo.get("year"), "keyword": memo["keyword"], "memo": memo["memo"]})
    return out


def overview(conn, subject, tax, unit):
    """한눈에: 출제 문항 수·출제 회차 수·가장 최근 출제 회차·회당 배점(전체 회차 기준)."""
    row = next((r for r in unit_profile(conn)["rows"] if (r["subject"], r["tax"], r["unit"]) == (subject, tax, unit)), None)
    latest = conn.execute("SELECT MAX(round) FROM questions WHERE subject=? AND tax=? AND unit=?", (subject, tax, unit)).fetchone()[0]
    return {"questions": row["questions"], "rounds": row["rounds"], "latest_round": latest, "points_per_round": row["points_per_round"]}


def is_full_sentence(text):
    """보기 조각('자산의 과소계상' 같은 명사구, 분개 줄)이 아니라 '…다' 로 끝나는 문장인가. 문항 물음과 함께 읽어야 뜻이 통하는 조각은 노트에서 뺀다."""
    return len(text) >= MIN_SENTENCE_LENGTH and text.rstrip(". ").endswith("다") and "(차)" not in text and "(대)" not in text


def unit_sentences(conn, subject, tax, unit):
    """시험에 나온 문장: 이 단원 기출의 맞는 문장·함정. 같은 문장은 합치고 최근 회차 → 많이 나온 순으로 SENTENCE_LIMIT 개."""
    rows = conn.execute("SELECT * FROM questions WHERE subject=? AND tax=? AND unit=?", (subject, tax, unit)).fetchall()
    right, traps, excluded = collect_sentences(rows)

    def pick(entries):
        groups = merge_sentences([e for e in entries if is_full_sentence(e[0])])
        groups.sort(key=lambda g: (-max(g["rounds"]), -g["count"]))
        return [{"text": g["text"], "sources": g["sources"], "count": g["count"], "latest_round": max(g["rounds"]), "tax_notice": g["tax_notice"]}
                for g in groups[:SENTENCE_LIMIT]]
    return {"right": pick(right), "traps": pick(traps), "excluded_count": len(excluded)}


def reviewed_sections(conn, unit):
    return {r["section"] for r in conn.execute("SELECT section FROM study_review WHERE user_id = ? AND unit = ?", (conn.user_id, unit))}


def get_status(conn, unit):
    row = conn.execute("SELECT status FROM study_progress WHERE user_id = ? AND unit = ?", (conn.user_id, unit)).fetchone()
    return row["status"] if row else ""


def get_note(conn, unit):
    """단원 노트 화면에 필요한 모든 것. 노트 파일이 없으면 note 가 None."""
    subject, tax, name = find_unit(conn, unit)
    note = load_note(subject, name)
    meanings = {e["term"]: e["meaning"] for e in load_glossary()}
    reviewed = reviewed_sections(conn, name)
    out = {"unit": name, "subject": subject, "tax": tax, "overview": overview(conn, subject, tax, name),
           "sentences": unit_sentences(conn, subject, tax, name), "status": get_status(conn, name), "note": None,
           "drafts": [s for s in AI_SECTIONS if s not in reviewed]}
    if note:
        formula = note.get("formula")
        if formula and formula.get("example_id"):
            row = conn.execute("SELECT * FROM questions WHERE id = ?", (formula["example_id"],)).fetchone()
            formula = {**formula, "example": public_question(row) if row else None}
        concept = note.get("concept") or {}
        out["note"] = {"concept": {"lines": concept.get("lines", []),
                                   "terms": [{"term": t, "meaning": meanings.get(t, "")} for t in concept.get("terms", [])]},
                       "practice": note.get("practice") or [], "formula": formula, "changes": note.get("changes") or [],
                       "change_memos": change_memos(tax, name, note) if subject == TAX_SUBJECT else [],
                       "change_gap": CHANGES_GAP if subject == TAX_SUBJECT else ""}
    return out


def changes_overview(conn):
    """'4년 사이 바뀐 세법 모아 보기': 세무 노트의 ⑥ 칸만 세목별로 모은다(쪽수 출처 포함). 단원에 연결되지 않은 메모는 따로 보인다."""
    taxes, linked = {}, set()
    for subject, tax, unit in unit_rows(conn):
        if subject != TAX_SUBJECT:
            continue
        note = load_note(subject, unit)
        items = [c for c in (note or {}).get("changes") or [] if isinstance(c, dict)]
        memos = change_memos(tax, unit, note)
        linked.update((m["keyword"], m["memo"]) for m in memos)
        taxes.setdefault(tax, []).append({"unit": unit, "items": items, "memos": memos})
    loose = [{"year": m.get("year"), "keyword": m["keyword"], "memo": m["memo"], "tax": m.get("tax")} for m in tax_changes() if (m["keyword"], m["memo"]) not in linked]
    return {"taxes": [{"tax": t, "units": u} for t, u in taxes.items()], "loose_memos": loose, "gap": CHANGES_GAP, "source": CHANGES_SOURCE}


def save_progress(conn, unit, status):
    """단원 진도(읽음·이해함)를 저장한다. 빈 값이면 되돌린다."""
    find_unit(conn, unit)
    if status not in STATUSES:
        raise ValueError("진도 값이 올바르지 않습니다.")
    with conn:
        conn.execute("INSERT INTO study_progress(user_id, unit, status, updated) VALUES (?,?,?,?) "
                     "ON CONFLICT(user_id, unit) DO UPDATE SET status=excluded.status, updated=excluded.updated", (conn.user_id, unit, status, clock.now()))
    return status


def set_review(conn, unit, section, reviewed):
    """AI 초안 칸을 '검토 완료'(reviewed=True)로 바꾸거나 되돌린다."""
    find_unit(conn, unit)
    if section not in AI_SECTIONS:
        raise ValueError("검토할 수 없는 칸입니다.")
    with conn:
        if reviewed:
            conn.execute("INSERT OR REPLACE INTO study_review(user_id, unit, section, updated) VALUES (?,?,?,?)", (conn.user_id, unit, section, clock.now()))
        else:
            conn.execute("DELETE FROM study_review WHERE user_id = ? AND unit = ? AND section = ?", (conn.user_id, unit, section))
    return sorted(reviewed_sections(conn, unit))


def _statuses(conn):
    return {r["unit"]: r["status"] for r in conn.execute("SELECT unit, status FROM study_progress WHERE user_id = ?", (conn.user_id,))}


def curriculum(conn):
    """과목 카드: 과목마다 단원 목록(회당 배점 큰 순)과 진도율. 진도율 = 읽음 또는 이해함으로 표시한 단원 ÷ 전체 단원."""
    statuses = _statuses(conn)
    points = {(r["subject"], r["tax"], r["unit"]): r["points_per_round"] for r in unit_profile(conn)["rows"]}
    cards = []
    for subject, label in CARDS:
        units = [{"unit": u, "tax": t, "points_per_round": points[(s, t, u)], "status": statuses.get(u, ""),
                  "has_note": load_note(s, u) is not None}
                 for s, t, u in unit_rows(conn) if s == subject]
        units.sort(key=lambda x: (-x["points_per_round"], x["unit"]))
        done = sum(1 for u in units if u["status"] in ("read", "understood"))
        cards.append({"subject": subject, "label": label, "units": units, "total": len(units), "done": done,
                      "understood": sum(1 for u in units if u["status"] == "understood"),
                      "progress": round(done / len(units), 3) if units else 0.0,
                      "taxes": sorted({u["tax"] for u in units if u["tax"]})})
    return cards


def roadmap(conn):
    """4년 만의 복귀 순서: 점수 = 회당 배점(전체 회차) × 최근 10회 출제율. 큰 순.
    오답노트에 남은 문항이 있는 단원은 점수와 상관없이 앞으로(오답 많은 순 → 점수 순)."""
    statuses = _statuses(conn)
    recent = {(r["subject"], r["tax"], r["unit"]): r["appear_rate"] for r in unit_profile(conn, LATEST_ROUNDS)["rows"]}
    wrong = {}
    for item in notebook(conn):
        wrong[item["unit"]] = wrong.get(item["unit"], 0) + 1
    rows = []
    for r in unit_profile(conn)["rows"]:
        key = (r["subject"], r["tax"], r["unit"])
        rate = recent.get(key, 0.0)
        rows.append({"unit": r["unit"], "subject": r["subject"], "tax": r["tax"], "points_per_round": r["points_per_round"],
                     "recent_rate": rate, "score": round(r["points_per_round"] * rate, 3), "status": statuses.get(r["unit"], ""),
                     "wrong_open": wrong.get(r["unit"], 0), "has_note": load_note(r["subject"], r["unit"]) is not None})
    rows.sort(key=lambda r: (-r["wrong_open"], -r["score"], r["unit"]))
    return rows
