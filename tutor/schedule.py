"""캘린더 스케줄러 API 의 계산: 한 달 달력(주 단위로 채운 격자)과 날짜 상세, 맨 위 요약(D-day·이번 달 달성률·연속 공부 일수).

한 달 달성률 = 그 달 안에서 오늘까지 계획이 있고 쉬는 날이 아닌 날들의 하루 달성률 평균(없으면 None).
달력은 일요일에 시작하는 주 격자다(앞뒤 달 날짜 칸은 in_month=False).
"""
from datetime import date

from . import carry, clock, daily, match, plan


def _grid_range(year, month):
    first = date(year, month, 1)
    last = date(year + (month == 12), month % 12 + 1, 1).toordinal() - 1
    start = first.toordinal() - (first.weekday() + 1) % 7
    end = last + (6 - (date.fromordinal(last).weekday() + 1) % 7)
    return first.toordinal(), last, start, end


def _slim(report, in_month):
    return {"date": report["date"], "day": report["day"], "weekday": report["weekday"], "state": report["state"], "pct": report["pct"],
            "summary": report["summary"], "edited": report["edited"], "carried": report["carried"], "in_month": in_month}


def header(conn, today, month_reports):
    settings = plan.get_settings(conn)
    done = [r["pct"] for r in month_reports if r["pct"] is not None and r["day"] <= today]
    return {"today": clock.iso(today), "exam_date": settings["exam_date"],
            "dday": settings["exam_day"] - today if settings["exam_day"] else None,
            "month_pct": round(sum(done) / len(done)) if done else None, "month_days_counted": len(done),
            "streak": daily.streak(conn, today),
            "carry": {k: v for k, v in carry.summary(conn, today).items() if k != "items"}}


def month(conn, year, month_number, today=None):
    today = clock.today() if today is None else today
    first, last, start, end = _grid_range(year, month_number)
    reports = match.report_range(conn, start, end, today)
    return {"year": year, "month": month_number, "today": clock.iso(today),
            "days": [_slim(r, first <= r["day"] <= last) for r in reports],
            "header": header(conn, today, [r for r in reports if first <= r["day"] <= last])}


def day_detail(conn, day, today=None):
    """날짜 상세: 계획 항목별 목표 대비 실제 + 그날 실제 기록(푼 문항·O/X 정오·읽은 노트·모의고사 점수)."""
    today = clock.today() if today is None else today
    report = match.report(conn, day, today)
    return {"date": report["date"], "state": report["state"], "pct": report["pct"], "summary": report["summary"], "edited": report["edited"],
            "is_today": day == today, "items": report["items"], "actual": match.details(report["actual"]),
            "rest": report["state"] == "rest", "editable": report["state"] != "exam"}
