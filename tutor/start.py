"""시작하기(/start): 처음 로그인한 사람(계획 없음)에게 이론 범위·과목별 규모·추천 학습 순서 상위 8개를 한 화면으로 보여 준다.

숫자는 모두 기출 DB 에서 계산한다(단원 수 = unit_profile 의 단원, 회당 평균 배점 = 단원별 회당 배점의 합).
추천 순서는 study.roadmap 를 그대로 쓴다(새 기준을 만들지 않는다).
"""
from . import plan, study
from .analysis import unit_profile

TOP = 8
BASIS = "오답노트에 남은 문항이 있는 단원을 먼저, 그다음은 '회당 배점 × 최근 10회 출제율'이 큰 순서입니다."


def scope(conn):
    """[{subject, units, points_per_round, taxes: [{tax, units, points_per_round}]}] — 과목은 기출에 나온 순서(재무·원가·세무)로."""
    order = {"재무회계": 0, "원가회계": 1, "세무회계": 2}
    subjects = {}
    for r in unit_profile(conn)["rows"]:
        s = subjects.setdefault(r["subject"], {"subject": r["subject"], "units": 0, "points": 0.0, "taxes": {}})
        s["units"] += 1
        s["points"] += r["points_per_round"]
        if r["tax"]:
            t = s["taxes"].setdefault(r["tax"], {"tax": r["tax"], "units": 0, "points": 0.0})
            t["units"] += 1
            t["points"] += r["points_per_round"]
    out = []
    for s in sorted(subjects.values(), key=lambda s: (order.get(s["subject"], 9), s["subject"])):
        out.append({"subject": s["subject"], "units": s["units"], "points_per_round": round(s["points"], 1),
                    "taxes": [{"tax": t["tax"], "units": t["units"], "points_per_round": round(t["points"], 1)} for t in sorted(s["taxes"].values(), key=lambda t: t["tax"])]})
    return out


def overview(conn):
    top = [{"rank": i, "unit": r["unit"], "subject": r["subject"], "tax": r["tax"], "points_per_round": r["points_per_round"],
            "recent_rate": r["recent_rate"], "wrong_open": r["wrong_open"]} for i, r in enumerate(study.roadmap(conn)[:TOP], 1)]
    return {"scope": scope(conn), "top": top, "basis": BASIS, "has_plan": plan.configured(conn)}
