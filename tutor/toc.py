"""문제 목차: 전체 회차 이론 문항을 과목 › 단원으로 묶는다. 정답·해설·보기는 넣지 않는다(목록은 문제 첫 줄만)."""
from .records import first_line

SUBJECT_ORDER = ("재무회계", "원가회계", "세무회계")


def build_toc(conn):
    """[{subject, count, units:[{label, tax, unit, count, round_count, items:[{id, round, number, first_line}]}]}]."""
    rows = conn.execute("""SELECT id, round, number, subject, tax, unit, question FROM questions
                           ORDER BY round DESC, number""").fetchall()
    grouped = {}
    for r in rows:
        grouped.setdefault(r["subject"], {}).setdefault((r["tax"], r["unit"]), []).append(r)
    subjects = sorted(grouped, key=lambda s: (SUBJECT_ORDER.index(s) if s in SUBJECT_ORDER else 99, s))
    toc = []
    for subject in subjects:
        units = []
        for (tax, unit), items in sorted(grouped[subject].items()):
            units.append({"label": " › ".join(p for p in (tax, unit) if p), "tax": tax, "unit": unit,
                          "count": len(items), "round_count": len({i["round"] for i in items}),
                          "items": [{"id": i["id"], "round": i["round"], "number": i["number"],
                                     "first_line": first_line(i["question"])} for i in items]})
        toc.append({"subject": subject, "count": sum(u["count"] for u in units), "units": units})
    return toc
