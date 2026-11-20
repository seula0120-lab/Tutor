"""계획 세우기: 시험일·시작일·쉬는 요일로 날짜별 계획(plans 표)을 자동으로 만들고, 사람이 고친 날은 지킨다.

계획 생성 규칙 (generate)
1. 만들 범위 = max(시작일, 오늘) ~ 시험 전날. 오늘 이미 공부한 기록이 있으면 오늘은 건드리지 않고 내일부터(한 일이 계획과 어긋나지 않게).
   지난 날 계획은 기록으로 남기고 다시 만들지 않는다.
2. 사람이 고친 날(edited=1 줄이 있는 날, '그날 쉬기' 포함)은 덮어쓰지 않는다. 그 밖의 앞날 계획은 지우고 새로 만든다.
3. 쉬는 요일은 계획을 두지 않는다. 시험 전날부터 거꾸로 final_days 일(기본 7)은 '마무리 기간': 모의고사·복습 위주.
   - 마무리 기간: 복습(하루 max(복습 분량, 20)) + 이틀에 한 번 모의고사 1회, 모의고사가 없는 날은 단원 무관 기출 10문제. 시험 전날은 복습만.
4. 나머지 공부일에는 복귀 순서(study.roadmap)대로 단원을 나눠 담는다.
   - 노트가 있는 단원만. '이해함' 단원은 맨 뒤로 미룬다. 사람이 고친 날에 노트가 잡힌 단원과, 지난 날 노트가 잡혔고 실제로 읽음·이해함 표시를 한 단원은 첫 바퀴에서 뺀다(못 읽은 단원은 다시 담긴다).
   - 하루 노트 수 k = min(5, max(설정의 하루 노트 수, ceil(남은 단원 수 ÷ 공부일 수))). 단원 하나마다 노트 1 + O/X + 기출(설정의 하루 O/X·기출 개수, 단원 문항이 적으면 그 수).
   - 첫 바퀴가 끝나고도 날이 남으면 복귀 순서를 다시 돌며 O/X·기출만 잡는다(노트는 다시 잡지 않는다).
   - 날이 모자라 못 담은 단원은 결과의 unscheduled 로 알린다.
5. 평일마다 복습 review_per_day(기본 10)개.
"""
import json
import math

from . import clock, match, ox, study
from .quiz import list_units

DEFAULTS = {"final_days": 7, "review_per_day": 10}
LIMITS = {"final_days": (0, 30), "review_per_day": (0, 50)}
KIND_LIMITS = {"note": (1, 1), "ox": (1, 200), "quiz": (1, 100), "review": (1, 200), "mock": (1, 5)}
MAX_NOTES_PER_DAY = 5
FINAL_REVIEW_MIN, FINAL_QUIZ = 20, 10


# ------------------------------------------------------------------ 설정
def _raw_settings(conn):
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM plan_settings WHERE user_id = ?", (conn.user_id,))}


def get_settings(conn):
    raw = _raw_settings(conn)
    day = lambda k: int(raw[k]) if raw.get(k) else None
    return {"exam_day": day("exam_day"), "start_day": day("start_day"),
            "exam_date": clock.iso(day("exam_day")) if day("exam_day") else None,
            "start_date": clock.iso(day("start_day")) if day("start_day") else None,
            "rest_days": sorted(int(x) for x in raw.get("rest_days", "").split(",") if x != ""),
            "final_days": int(raw.get("final_days", DEFAULTS["final_days"])),
            "review_per_day": int(raw.get("review_per_day", DEFAULTS["review_per_day"]))}


def save_settings(conn, values, today=None):
    """설정 저장. 시험일은 오늘 이후, 시작일은 시험일 이전이어야 한다. 잘못된 값은 ValueError."""
    today = clock.today() if today is None else today
    current = get_settings(conn)
    out = {}
    if "exam_date" in values:
        out["exam_day"] = clock.parse_iso(values["exam_date"])
        if out["exam_day"] <= today:
            raise ValueError("시험일은 오늘 이후여야 합니다.")
    if values.get("start_date"):
        out["start_day"] = clock.parse_iso(values["start_date"])
    elif "start_date" in values:
        out["start_day"] = None
    exam, start = out.get("exam_day", current["exam_day"]), out.get("start_day", current["start_day"])
    if exam and start and start >= exam:
        raise ValueError("공부 시작일은 시험일보다 앞이어야 합니다.")
    if "rest_days" in values:
        days = values["rest_days"]
        if not isinstance(days, list) or any(isinstance(x, bool) or not isinstance(x, int) or not 0 <= x <= 6 for x in days):
            raise ValueError("쉬는 요일은 0(월)~6(일) 숫자 목록이어야 합니다.")
        if len(set(days)) >= 7:
            raise ValueError("모든 요일을 쉴 수는 없습니다.")
        out["rest_days"] = ",".join(str(x) for x in sorted(set(days)))
    for key, (low, high) in LIMITS.items():
        if key in values:
            try:
                number = int(values[key])
            except (TypeError, ValueError):
                raise ValueError("마무리 기간·복습 분량은 숫자여야 합니다.")
            if not low <= number <= high:
                raise ValueError(f"{'마무리 기간(일)' if key == 'final_days' else '하루 복습 개수'}는 {low}~{high} 사이여야 합니다.")
            out[key] = number
    with conn:
        for key, value in out.items():
            if value is None:
                conn.execute("DELETE FROM plan_settings WHERE user_id = ? AND key = ?", (conn.user_id, key))
            else:
                conn.execute("INSERT INTO plan_settings(user_id, key, value) VALUES (?,?,?) ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value",
                             (conn.user_id, key, str(value)))
    return get_settings(conn)


# ------------------------------------------------------------------ 생성
def _edited_days(conn, first):
    return {r["day"] for r in conn.execute("SELECT DISTINCT day FROM plans WHERE user_id = ? AND edited = 1 AND day >= ?", (conn.user_id, first))}


def generate(conn, today=None):
    """계획을 (다시) 만든다. 규칙은 모듈 설명 참고. 결과 요약을 돌려준다."""
    today = clock.today() if today is None else today
    s = get_settings(conn)
    if not s["exam_day"]:
        raise ValueError("시험일을 먼저 저장하세요.")
    exam = s["exam_day"]
    if exam <= today:
        raise ValueError("시험일이 이미 지났습니다. 새 시험일을 저장하세요.")
    first = max(s["start_day"] or today, today)
    if first == today and match.has_activity(match.actuals(conn, today, today)[today]):
        first = today + 1
    last = exam - 1
    edited = _edited_days(conn, first)
    rest = set(s["rest_days"])
    daily = _daily_settings(conn)

    # 첫 바퀴에서 뺄 단원: 사람이 고친 날에 노트가 잡힌 단원, 그리고 지난 날 노트가 잡혔고 실제로 읽음·이해함 표시를 한 단원(못 읽은 단원은 다시 담긴다)
    done_units = {r["unit"] for r in conn.execute("SELECT unit FROM study_progress WHERE user_id = ? AND status != ''", (conn.user_id,))}
    kept_notes = {r["unit"] for r in conn.execute("SELECT unit, day, edited FROM plans WHERE user_id = ? AND kind = 'note' AND (day < ? OR edited = 1)", (conn.user_id, first))
                  if r["edited"] or r["unit"] in done_units}
    roadmap = [r for r in study.roadmap(conn) if r["has_note"]]
    order = [r for r in roadmap if r["status"] != "understood"] + [r for r in roadmap if r["status"] == "understood"]
    first_pass = [r["unit"] for r in order if r["unit"] not in kept_notes]
    cycle = [r["unit"] for r in order]
    ox_total = {u["unit"]: u["total"] for u in ox.stats(conn)["units"]}
    q_total = {r["unit"]: r["count"] for r in list_units(conn)}

    days = [d for d in range(first, last + 1) if d not in edited and clock.weekday(d) not in rest]
    final_start = exam - s["final_days"] if s["final_days"] else exam
    final = [d for d in days if d >= final_start]
    study_days = [d for d in days if d < final_start]
    notes_per_day = min(MAX_NOTES_PER_DAY, max(daily["daily_notes"], math.ceil(len(first_pass) / len(study_days)) if study_days else 1))

    rows = []                                    # (day, kind, unit, target)
    feed = [(u, True) for u in first_pass]
    cursor, cycle_pos = 0, 0

    def next_entry():
        nonlocal cursor, cycle_pos
        if cursor < len(feed):
            cursor += 1
            return feed[cursor - 1]
        if not cycle:
            return None
        unit = cycle[cycle_pos % len(cycle)]
        cycle_pos += 1
        return unit, False

    for d in study_days:
        for _ in range(notes_per_day):
            entry = next_entry()
            if entry is None:
                break
            unit, with_note = entry
            if with_note:
                rows.append((d, "note", unit, 1))
            if min(daily["daily_ox"], ox_total.get(unit, 0)) > 0:
                rows.append((d, "ox", unit, min(daily["daily_ox"], ox_total[unit])))
            if min(daily["daily_questions"], q_total.get(unit, 0)) > 0:
                rows.append((d, "quiz", unit, min(daily["daily_questions"], q_total[unit])))
        if s["review_per_day"]:
            rows.append((d, "review", "", s["review_per_day"]))
    for n, d in enumerate(final):
        rows.append((d, "review", "", max(s["review_per_day"], FINAL_REVIEW_MIN)))
        if d != last and n % 2 == 0:
            rows.append((d, "mock", "", 1))
        elif d != last:
            rows.append((d, "quiz", "", FINAL_QUIZ))
    unscheduled = first_pass[cursor:]

    with conn:
        conn.execute("DELETE FROM plans WHERE user_id = ? AND day >= ? AND day NOT IN (SELECT day FROM plans WHERE user_id = ? AND edited = 1)",
                     (conn.user_id, first, conn.user_id))
        conn.executemany("INSERT INTO plans(user_id, day, kind, unit, target, edited) VALUES (?,?,?,?,?,0)",
                         [(conn.user_id, d, k, u, t) for d, k, u, t in rows])
    return {"from": clock.iso(first), "to": clock.iso(last), "study_days": len(study_days), "final_days": len(final),
            "rest_days": sum(1 for d in range(first, last + 1) if clock.weekday(d) in rest and d not in edited),
            "kept_edited_days": len(edited & set(range(first, last + 1))), "notes_per_day": notes_per_day,
            "units_scheduled": cursor, "unscheduled": unscheduled}


def _daily_settings(conn):
    from . import daily
    return daily.get_settings(conn)


# ------------------------------------------------------------------ 직접 고치기
def unit_options(conn):
    """고르기 목록: 모든 단원(과목 순)."""
    notes = {r["unit"] for r in study.roadmap(conn) if r["has_note"]}
    return [{"unit": u, "subject": s, "tax": t, "has_note": u in notes} for s, t, u in study.unit_rows(conn)]


def _clean_items(conn, items):
    clean, seen = [], set()
    if not isinstance(items, list):
        raise ValueError("항목 목록이 필요합니다.")
    for item in items:
        if not isinstance(item, dict) or item.get("kind") not in KIND_LIMITS:
            raise ValueError("항목 종류는 note·ox·quiz·review·mock 중 하나여야 합니다.")
        kind, unit = item["kind"], str(item.get("unit") or "")
        if kind in ("note", "ox") and not unit:
            raise ValueError(f"{match.LABELS[kind]}는 단원을 골라야 합니다.")
        if kind in ("review", "mock"):
            unit = ""
        if unit:
            study.find_unit(conn, unit)
        try:
            target = 1 if kind == "note" else int(item.get("target"))
        except (TypeError, ValueError):
            raise ValueError("목표 수량은 숫자여야 합니다.")
        low, high = KIND_LIMITS[kind]
        if not low <= target <= high:
            raise ValueError(f"{match.LABELS[kind]} 목표는 {low}~{high} 사이여야 합니다.")
        if (kind, unit) in seen:
            raise ValueError("같은 항목이 두 번 들어 있습니다.")
        seen.add((kind, unit))
        clean.append((kind, unit, target))
    return clean


def edit_day(conn, day, items=None, rest=False):
    """그날 계획을 직접 바꾼다(항목 전체 교체 또는 '그날 쉬기'). 고친 날은 edited=1 로 남아 다시 생성해도 지켜진다."""
    if rest:
        clean = [("rest", "", 0)]
    else:
        clean = _clean_items(conn, items)
        if not clean:
            raise ValueError("항목이 없으면 '그날 쉬기'로 저장하세요.")
    with conn:
        conn.execute("DELETE FROM plans WHERE user_id = ? AND day = ?", (conn.user_id, day))
        conn.executemany("INSERT INTO plans(user_id, day, kind, unit, target, edited) VALUES (?,?,?,?,?,1)",
                         [(conn.user_id, day, k, u, t) for k, u, t in clean])


def reset_day(conn, day):
    """고친 날을 자동 계획으로 되돌린다(그날 줄을 지운다). 이어서 generate 를 부르면 다시 채워진다."""
    with conn:
        conn.execute("DELETE FROM plans WHERE user_id = ? AND day = ?", (conn.user_id, day))


def today_rows(conn, day):
    return match.plan_rows_by_day(conn, day, day).get(day, [])


def configured(conn):
    """계획 기능을 쓰는 중인가(시험일을 저장했거나 계획 줄이 있다)."""
    return bool(_raw_settings(conn).get("exam_day")) or conn.execute("SELECT 1 FROM plans WHERE user_id = ? LIMIT 1", (conn.user_id,)).fetchone() is not None
