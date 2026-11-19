"""문제 분석 탭: 단원별 출제 비율과 회당 배점을 센다. 기록(풀이 이력)은 쓰지 않는다."""
from .search import scope_rounds


def unit_profile(conn, round_limit=None):
    """범위 안 회차에서 단원(과목›세목›단원)별 출제 통계를 돌려준다. 회당 배점이 큰 순.

    각 행: label, subject, tax, unit, questions(문항 수), rounds(출제된 회차 수), appear_rate(회차 중 출제 비율),
           share(전체 문항 중 비율), points_per_round(회당 평균 배점).
    """
    rounds = scope_rounds(conn, round_limit)
    if not rounds:
        return {"rounds": 0, "total_questions": 0, "rows": []}
    marks = ",".join("?" * len(rounds))
    data = conn.execute(
        f"""SELECT subject, tax, unit, COUNT(*) AS questions, COUNT(DISTINCT round) AS rounds_seen,
                   SUM(points) AS points
            FROM questions WHERE round IN ({marks}) GROUP BY subject, tax, unit""", rounds).fetchall()
    total = sum(r["questions"] for r in data)
    rows = [{
        "label": " › ".join(p for p in (r["subject"], r["tax"], r["unit"]) if p),
        "subject": r["subject"], "tax": r["tax"], "unit": r["unit"],
        "questions": r["questions"], "rounds": r["rounds_seen"],
        "appear_rate": round(r["rounds_seen"] / len(rounds), 3),
        "share": round(r["questions"] / total, 3),
        "points_per_round": round(r["points"] / len(rounds), 2),
    } for r in data]
    rows.sort(key=lambda r: (-r["points_per_round"], r["label"]))
    return {"rounds": len(rounds), "total_questions": total, "rows": rows}
