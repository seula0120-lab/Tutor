"""회차별 시행일(data/exam_dates.json, scripts/extract_exam_dates.py 가 원본 표지에서 뽑음). 못 찾은 회차는 파일에 없고, 없으면 추정하지 않는다.

DB 의 exam_dates 표는 bank 와 함께 적재 때 채워지는 파생 데이터다(load_bank). 화면·계산은 이 표를 읽는다.
날짜는 clock 처럼 정수 일 번호(date.toordinal)로 다룬다.
"""
import json
from datetime import date
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "exam_dates.json"
RECENT_MONTHS = 18   # '최근' 의 시행일 기준: 가장 최근 시행일부터 18개월 안. 실제 자료에서 옛 규칙(최근 10회)과 같은 회차 묶음이 된다.


def read(path=PATH):
    """{회차: {exam_date, source, page, text}}. 파일이 없거나 형식이 틀리면 빈 dict."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for entry in data if isinstance(data, list) else []:
        try:
            date.fromisoformat(entry["exam_date"])
            out[int(entry["round"])] = entry
        except (KeyError, TypeError, ValueError):
            continue
    return out


def fill(conn, rounds, path=PATH):
    """exam_dates 표를 다시 채운다(적재한 회차 rounds 의 것만). load_bank 안에서 부른다."""
    wanted = set(rounds)
    conn.execute("DELETE FROM exam_dates")
    conn.executemany("INSERT INTO exam_dates(round, exam_date, source, page) VALUES (?,?,?,?)",
                     [(n, e["exam_date"], e.get("source", ""), e.get("page")) for n, e in sorted(read(path).items()) if n in wanted])


def days(conn):
    """{회차: 시행일 일 번호}."""
    return {r["round"]: date.fromisoformat(r["exam_date"]).toordinal() for r in conn.execute("SELECT round, exam_date FROM exam_dates")}


def label(day):
    """일 번호 → '2026년 10월 시행 시험 기준'."""
    d = date.fromordinal(day)
    return f"{d.year}년 {d.month}월 시행 시험 기준"


def recent_cutoff(day_by_round):
    """'최근' 으로 칠 가장 이른 시행일(일 번호). 시행일이 하나도 없으면 None."""
    if not day_by_round:
        return None
    latest = date.fromordinal(max(day_by_round.values()))
    months = latest.year * 12 + latest.month - 1 - RECENT_MONTHS
    year, month = divmod(months, 12)
    month += 1
    last_day = (date(year + (month == 12), month % 12 + 1, 1) - date(year, month, 1)).days
    return date(year, month, min(latest.day, last_day)).toordinal()


def is_recent(round_no, latest_round, day_by_round, latest_rounds=10):
    """회차가 '최근' 인가. 시행일이 있는 회차(와 기준이 되는 최신 회차)는 시행일 기준, 시행일이 없으면 옛 규칙(최신 회차 − latest_rounds 보다 큰 회차)."""
    cutoff = recent_cutoff(day_by_round)
    if cutoff is not None and round_no in day_by_round:
        return day_by_round[round_no] >= cutoff
    return round_no > latest_round - latest_rounds
