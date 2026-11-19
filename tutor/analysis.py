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


MIN_SOLVED = 5   # 단원에서 서로 다른 문항을 이만큼 풀어야 정답률을 믿는다


def study_order(conn, round_limit=None):
    """공부 순서: 단원별 회당 예상 손실 점수 = 회당 배점 × (1 − 내 정답률), 큰 순.

    정답률 = 정답 기록 수 ÷ 풀이 기록 수(확인만 한 기록은 제외). 푼 문항(서로 다른 문항)이 MIN_SOLVED 개 미만이면
    정답률을 지어내지 않고 '기록 부족'으로 두며, 그런 단원은 표의 맨 아래에 회당 배점 순으로 둔다.
    """
    from .records import unit_stats
    stats = unit_stats(conn)
    rows = []
    for unit in unit_profile(conn, round_limit)["rows"]:
        stat = stats.get((unit["subject"], unit["tax"], unit["unit"]))
        solved = stat["questions"] if stat else 0
        enough = solved >= MIN_SOLVED
        accuracy = stat["correct"] / stat["attempts"] if enough else None
        rows.append({"label": unit["label"], "subject": unit["subject"], "tax": unit["tax"], "unit": unit["unit"],
                     "points_per_round": unit["points_per_round"], "solved_questions": solved,
                     "accuracy": None if accuracy is None else round(accuracy, 3),
                     "expected_loss": None if accuracy is None else round(unit["points_per_round"] * (1 - accuracy), 2),
                     "status": "ok" if enough else "기록 부족"})
    rows.sort(key=lambda r: (r["expected_loss"] is None,
                             -(r["expected_loss"] if r["expected_loss"] is not None else 0), -r["points_per_round"], r["label"]))
    return {"min_solved": MIN_SOLVED, "rows": rows}
