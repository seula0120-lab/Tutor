"""O/X 퀴즈: 기출의 맞는 문장(O)과 함정 문장(X)을 한 문장씩 O/X 로 맞힌다.

문장 출처는 요약 카드·공부 노트와 같은 모으기(summary.collect_sentences)다. 그래서 조합·계산·식별형·판별불가·전항 정답 문항과
'…다' 로 끝나지 않는 조각 문장은 들어가지 않는다. 같은 말을 한 문장끼리는 합치고, 합친 문장의 출처는 모두 보여 준다.
같은 글이 맞는 문장과 함정 양쪽에 있으면(개정 전후 답이 다른 경우 등) 어느 쪽이 맞는지 알 수 없어 뺀다.

세무 문장은 최근 10회(LATEST_ROUNDS) 것이 먼저 나오고, 그보다 옛 회차에만 있는 문장에는 '세법 개정 확인 필요' 안내가 붙는다.
풀이는 records 에 question_id='ox:<문장 키>', source='ox' 로 남긴다(오답노트·간격 복습과 같은 기록).
"""
import hashlib
import json
import random

from . import records
from .notice import tax_notice
from .quiz import NO_EXPLANATION, explanation_of, get_row
from .search import LATEST_ROUNDS
from .study import is_full_sentence
from .summary import collect_sentences, merge_sentences, normalize

TAX_SUBJECT = "세무회계"
PREFIX = "ox:"
OLD_TAX_LABEL = "세법 개정 확인 필요"
_cache = {}


def key_of(text):
    return hashlib.sha1(normalize(text).encode("utf-8")).hexdigest()[:12]


def record_id(key):
    return PREFIX + key


def _signature(conn):
    path = conn.execute("PRAGMA database_list").fetchone()["file"]
    count, size = conn.execute("SELECT COUNT(*), TOTAL(LENGTH(question) + LENGTH(choices) + LENGTH(answer)) FROM questions").fetchone()
    return path, count, size


def pool(conn):
    """문장 은행 {키: 문장 dict}. 문제은행이 그대로면 한 번만 만든다."""
    signature = _signature(conn)
    if _cache.get("signature") == signature:
        return _cache["items"]
    rows = conn.execute("SELECT * FROM questions").fetchall()
    by_id = {r["id"]: r for r in rows}
    latest = max((r["round"] for r in rows), default=0)
    right, traps, _ = collect_sentences(rows)

    def groups(entries):
        return merge_sentences([e for e in entries if is_full_sentence(e[0])])
    right_groups, trap_groups = groups(right), groups(traps)
    right_keys = {key_of(g["text"]) for g in right_groups}
    trap_keys = {key_of(g["text"]) for g in trap_groups}
    clash = right_keys & trap_keys
    items = {}
    for truth, found in ((True, right_groups), (False, trap_groups)):
        for g in found:
            key = key_of(g["text"])
            if key in clash:
                continue
            head = by_id[g["sources"][0]]                    # 출처는 최근 회차부터 들어 있다
            latest_round = max(g["rounds"])
            old_tax = head["subject"] == TAX_SUBJECT and latest_round <= latest - LATEST_ROUNDS
            items[key] = {"key": key, "text": g["text"], "truth": truth, "sources": g["sources"], "count": g["count"],
                          "latest_round": latest_round, "subject": head["subject"], "tax": head["tax"], "unit": head["unit"],
                          "old_tax": old_tax, "tax_label": (g["tax_notice"] or OLD_TAX_LABEL) if old_tax else ""}
    _cache.update(signature=signature, items=items)
    return items


def public_item(item):
    """화면에 줄 문장: 정답(truth)과 해설은 뺀다."""
    return {k: item[k] for k in ("key", "text", "subject", "tax", "unit", "latest_round", "old_tax", "tax_label")}


def stats(conn):
    """과목별·단원별 O/X 문장 수."""
    subjects, units = {}, {}
    for item in pool(conn).values():
        side = "o" if item["truth"] else "x"
        for bucket, name in ((subjects, item["subject"]), (units, (item["subject"], item["tax"], item["unit"]))):
            bucket.setdefault(name, {"o": 0, "x": 0})[side] += 1
    return {"subjects": [{"subject": s, **c, "total": c["o"] + c["x"]} for s, c in sorted(subjects.items())],
            "units": [{"subject": s, "tax": t, "unit": u, **c, "total": c["o"] + c["x"]} for (s, t, u), c in sorted(units.items())]}


def _answered_correctly(conn):
    return {r["question_id"][len(PREFIX):] for r in conn.execute(
        "SELECT DISTINCT question_id FROM records WHERE source = 'ox' AND correct = 1")}


def pick(conn, subject=None, tax=None, unit=None, count=20, rng=random):
    """조건에 맞는 문장 count 개의 키 목록. O 와 X 를 반반(모자라면 다른 쪽으로), 세무는 최근 10회 문장 먼저, 아직 못 맞힌 문장 먼저."""
    solved = _answered_correctly(conn)
    found = [i for i in pool(conn).values() if all(not want or i[field] == want for field, want in (("subject", subject), ("tax", tax), ("unit", unit)))]
    rng.shuffle(found)
    found.sort(key=lambda i: (i["old_tax"], i["key"] in solved))
    half = count // 2
    chosen = [i for i in found if i["truth"]][:count - half] + [i for i in found if not i["truth"]][:half]
    if len(chosen) < count:
        rest = [i for i in found if i not in chosen]
        chosen += rest[:count - len(chosen)]
    rng.shuffle(chosen)
    return [public_item(i) for i in chosen[:count]]


def answer(conn, key, choice):
    """O/X 를 채점하고 풀이 기록을 남긴다. X(함정) 문장이면 그 문항의 공식 해설(있을 때)을 함께 준다."""
    item = pool(conn).get(key)
    if item is None:
        return {"error": "없는 문장입니다."}
    if choice not in ("O", "X"):
        return {"error": "O 또는 X 를 골라야 합니다."}
    correct = (choice == "O") == item["truth"]
    records.save(conn, record_id(key), choice, correct, source="ox")
    explanation = ""
    if not item["truth"]:
        for source in item["sources"]:
            text = explanation_of(get_row(conn, source))
            if text != NO_EXPLANATION:
                explanation = text
                break
    return {"key": key, "correct": correct, "truth": item["truth"], "text": item["text"], "sources": item["sources"],
            "explanation": explanation, "old_tax": item["old_tax"], "tax_label": item["tax_label"]}
