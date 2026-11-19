"""주제 요약 카드: 검색된 관련 기출에서 '맞는 문장'과 '자주 나온 함정(틀린 문장)'을 모은다. API 를 쓰지 않는다.

흐름(한 방향): 검색 결과 중 관련 기출(related_results) → 유형 판별(question_type) →
  (부정형·긍정형만) 보기를 맞는/틀린 문장으로 나누기 → 비슷한 문장 합치기 →
  질문 핵심어가 든 문장만 남겨 핵심어를 많이 맞힌 순으로 → 출제 현황과 함께 카드로.
조합형·계산형·판별불가 문항은 문장 요약에서 빼고 목록으로만 돌려준다.
이 파일은 DB 를 읽기만 하고 아무것도 고치지 않는다.
"""
import json
import math
import re
from collections import Counter
from difflib import SequenceMatcher

from .notice import TAX_SUBJECT, tax_notice
from .question_type import CALCULATION, COMBINATION, NEGATIVE, POSITIVE, UNKNOWN, classify
from .quiz import accepted_answers

SIMILAR_RATIO = 0.9       # 이 이상 비슷하면 같은 문장으로 합친다(공백·문장부호 무시)
SENTENCE_LIMIT = 10       # 카드에 보여 줄 문장 수(맞는 문장·함정 각각)
EXCLUDED_KIND = {COMBINATION: "조합형", CALCULATION: "계산형", UNKNOWN: "판별불가"}


def related_results(results):
    """관련 기출만 남긴다: 1등 결과가 맞힌 낱말 수의 절반(올림) 이상을 맞힌 결과.
    '처리' 같은 흔한 낱말 하나만 맞은 엉뚱한 문항이 요약에 섞이지 않게 하려는 기준이다."""
    if not results:
        return []
    needed = max(1, math.ceil(len(results[0]["matched"]) / 2))
    return [r for r in results if len(r["matched"]) >= needed]


def normalize(sentence):
    """비교용 글: 공백과 문장부호를 뺀다."""
    return re.sub(r"[\s.,·ㆍ()\[\]「」'\"“”‘’]", "", sentence)


def is_similar(a, b):
    """두 문장이 같은 문장으로 볼 만큼 비슷한가. 부정('않')이 한쪽에만 있으면 뜻이 반대일 수 있어 합치지 않는다."""
    na, nb = normalize(a), normalize(b)
    if na == nb:
        return True
    if ("않" in na) != ("않" in nb) or ("아니" in na) != ("아니" in nb):
        return False
    matcher = SequenceMatcher(None, na, nb)
    return matcher.quick_ratio() >= SIMILAR_RATIO and matcher.ratio() >= SIMILAR_RATIO


def split_sentences(row, kind):
    """부정형·긍정형 문항의 보기를 (맞는 문장, 틀린 문장) 으로 나눈다. 정답 보기 번호(복수정답 포함)를 기준으로 한다."""
    answers = accepted_answers(row["answer"])
    choices = json.loads(row["choices"])
    answer_texts = [c.strip() for i, c in enumerate(choices, 1) if str(i) in answers]
    other_texts = [c.strip() for i, c in enumerate(choices, 1) if str(i) not in answers]
    return (other_texts, answer_texts) if kind == NEGATIVE else (answer_texts, other_texts)  # 부정형: 정답 = 틀린 문장


def merge_sentences(entries):
    """[(문장, 출처 id, 회차, 세무 여부)] 를 비슷한 문장끼리 합친다.

    합친 문장은 가장 최근 회차의 글을 대표로 쓰고, 출처는 모두 모은다. 많이 나온 문장이 먼저, 같으면 최근 회차가 먼저.
    """
    groups = []
    for text, source, round_no, is_tax in sorted(entries, key=lambda e: -e[2]):  # 최근 회차부터 넣어 대표를 최신으로
        group = next((g for g in groups if is_similar(g["text"], text)), None)
        if group is None:
            group = {"text": text, "sources": [], "rounds": [], "tax": False}
            groups.append(group)
        group["sources"].append(source)
        group["rounds"].append(round_no)
        group["tax"] = group["tax"] or is_tax
    for g in groups:
        g["count"] = len(g["sources"])
        latest_tax_round = max(g["rounds"]) if g["tax"] else None
        g["tax_notice"] = tax_notice(TAX_SUBJECT, latest_tax_round) if g["tax"] else None
        del g["tax"]
    groups.sort(key=lambda g: (-g["count"], -max(g["rounds"])))
    return groups


def matched_terms(text, terms):
    """문장에 들어 있는 질문 핵심어 목록(공백은 무시하고 비교). 핵심어는 질문에서 뽑은 낱말과 동의어로 넓힌 공식 용어다."""
    compact = normalize(text)
    found = [t for t in terms if normalize(t) and normalize(t) in compact]
    # 긴 핵심어 안에 통째로 들어 있는 짧은 핵심어는 따로 세지 않는다(예: '비정상공손' 속의 '정상공손').
    # 문장에서 긴 핵심어가 차지한 자리를 지운 뒤에도 남아 있을 때만 짧은 핵심어를 인정한다.
    kept = []
    for term in sorted(found, key=lambda t: -len(normalize(t))):
        key = normalize(term)
        remaining = compact
        for longer in kept:
            remaining = remaining.replace(normalize(longer), "\0")
        if key in remaining:
            kept.append(term)
    return [t for t in found if t in kept]


def covers_core_terms(conn, results, terms):
    """검색 결과 중 문제 글·보기에 질문 핵심어가 하나라도 들어 있는 문항이 있는가. 결과가 없으면 False."""
    for r in results:
        row = conn.execute("SELECT question, choices FROM questions WHERE id = ?", (r["id"],)).fetchone()
        if matched_terms(row["question"] + " " + " ".join(json.loads(row["choices"])), terms):
            return True
    return False


def select_sentences(groups, terms):
    """핵심어가 하나도 없는 문장은 빼고, 핵심어를 많이 맞힌 순 → 출제 횟수 → 최근 회차 순으로 SENTENCE_LIMIT 개만 돌려준다.
    원본 groups 는 고치지 않고 복사해서 matched(맞힌 핵심어)를 붙인다."""
    scored = [{**g, "matched": matched_terms(g["text"], terms)} for g in groups]
    kept = [g for g in scored if g["matched"]]
    kept.sort(key=lambda g: (-len(g["matched"]), -g["count"], -max(g["rounds"])))
    return kept[:SENTENCE_LIMIT]


def coverage(rows):
    """출제 현황: 관련 문항 수, 나온 회차 목록(최근 순), 가장 최근 회차, 단원별 문항 수."""
    rounds = sorted({r["round"] for r in rows}, reverse=True)
    units = Counter(r["unit"] for r in rows)
    return {"questions": len(rows), "rounds": rounds, "round_count": len(rounds),
            "latest_round": rounds[0] if rounds else None, "units": units.most_common(3)}


def build_summary(conn, results, terms):
    """검색 결과(점수 포함)와 질문 핵심어(terms, 동의어 확장 포함) → 요약 카드 dict.

    {"coverage", "right"(맞는 문장), "traps"(함정), "excluded"(조합·계산·판별불가 목록), "tax_notice"(카드 전체 안내 또는 None)}
    """
    rows = [conn.execute("SELECT * FROM questions WHERE id = ?", (i,)).fetchone() for i in (r["id"] for r in related_results(results))]
    right, traps, excluded = [], [], []
    for row in rows:
        kind = classify(row["question"], json.loads(row["choices"]))
        if kind not in (NEGATIVE, POSITIVE):
            excluded.append({"id": row["id"], "kind": EXCLUDED_KIND[kind], "question": row["question"]})
            continue
        is_tax = row["subject"] == TAX_SUBJECT
        good, bad = split_sentences(row, kind)
        right += [(s, row["id"], row["round"], is_tax) for s in good]
        traps += [(s, row["id"], row["round"], is_tax) for s in bad]
    has_tax = any(r["subject"] == TAX_SUBJECT for r in rows)
    latest_tax = max((r["round"] for r in rows if r["subject"] == TAX_SUBJECT), default=None)
    return {
        "coverage": coverage(rows),
        "right": select_sentences(merge_sentences(right), terms),
        "traps": select_sentences(merge_sentences(traps), terms),
        "excluded": excluded,
        "tax_notice": tax_notice(TAX_SUBJECT, latest_tax) if has_tax else None,
    }
