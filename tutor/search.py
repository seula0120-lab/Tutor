"""이론 기출 검색(기본 범위는 전체 회차): 질문 → 검색어 → (일상어 동의어 확장) → FTS5/LIKE 후보 → 점수 순 정렬.

흐름(한 방향): 질문 글 → extract_terms → 확장 낱말 추가 → 후보 찾기 → 점수 매기기 → 결과 목록.
3글자 이상 낱말은 FTS5 trigram, 1~2글자(손금·유보 등)는 LIKE 로 찾는다.
점수 = 낱말 가중치 × 희귀도(idf) × (질문 문장에 나오면 2배). 희귀한 낱말이 많이 맞을수록 위로 온다.
흔한 낱말(5% 초과 문항)은 점수를 절반으로 줄이고, 1등의 35% 에 못 미치는 결과는 보여 주지 않는다(docs/search_noise.md).
"""
import json
import math
import re

from .glossary import expand_everyday_words, load_glossary
from .notice import tax_notice

LATEST_ROUNDS = 10       # 선택 범위 "최신 10회분"의 회차 수
DEFAULT_ROUNDS = None    # 기본 검색 범위: 전체 회차(None). 숫자를 주면 최신 N회분
RESULT_LIMIT = 5
EXPANDED_WEIGHT = 1.5    # 사전에서 넓혀 온 공식 용어는 질문에 직접 쓴 낱말보다 믿을 만하다
STEM_BONUS = 2           # 질문 문장에 낱말이 나오면 점수 2배
COMMON_DF_RATIO = 0.05   # 범위 안 문항의 5% 보다 많은 문항에 든 낱말은 '흔한 낱말'(항목·대상·적용 등)
COMMON_DAMP = 0.5        # 흔한 낱말의 점수에 곱하는 값: 흔한 낱말 하나만 맞은 문항이 위로 오는 것을 줄인다
TAIL_CUT = 0.35          # 1등 점수의 35% 보다 낮은 결과는 뺀다(관련 문항이 적을 때 흔한 낱말로 채워지는 꼬리 제거)

# 낱말 끝에서 떼어 낼 조사·어미(긴 것부터 시도한다).
ENDINGS = ("이라는데", "라는데", "설명해줘", "알려줘", "해줘", "하면서", "에서는", "으로는", "이라고",
           "하는", "하면", "하고", "해서", "했는", "에서", "으로", "에게", "한테", "까지", "부터", "보다",
           "처럼", "이랑", "라는", "인가", "이야", "는데", "은", "는", "이", "가", "을", "를", "의",
           "에", "도", "와", "과", "로", "랑", "만", "해", "야")
STOPWORDS = {"설명", "알려", "뭐", "뭔", "뭐야", "뭔지", "어떻게", "어떤", "무슨", "언제", "어디", "얼마",
             "쉽게", "정리", "관련", "대해", "대한", "다음", "경우", "무엇", "질문", "문제", "기출",
             "알고", "싶어", "궁금", "있어", "있는", "되는", "되나", "돼", "할까", "하나", "이란", "에서"}


def extract_terms(query):
    """질문에서 검색어 목록을 뽑는다: 문장부호·조사·어미를 떼고, 2글자 미만과 불용어는 버린다."""
    terms = []
    for raw in query.split():
        token = re.sub(r"^[^\w]+|[^\w]+$", "", raw)
        token = _strip_ending(token)
        if len(token) >= 2 and token.casefold() not in STOPWORDS:
            terms.append(token)
    return list(dict.fromkeys(terms))


def _strip_ending(token):
    for ending in ENDINGS:
        if token.endswith(ending) and len(token) - len(ending) >= 2:
            return token[: -len(ending)]
    return token


def build_weighted_terms(query, entries):
    """[(낱말, 가중치)] 를 만든다. 사전에서 넓혀 온 공식 용어를 뒤에 붙인다(중복은 큰 가중치 하나)."""
    weights = {term: 1.0 for term in extract_terms(query)}
    for term in expand_everyday_words(query, entries):
        weights[term] = max(weights.get(term, 0), EXPANDED_WEIGHT)
    return weights


def scope_rounds(conn, round_limit):
    """검색 범위의 회차 목록. round_limit 이 None 이면 적재된 모든 회차, 아니면 최신 N회분."""
    rounds = [r[0] for r in conn.execute("SELECT DISTINCT round FROM questions ORDER BY round DESC")]
    return rounds if round_limit is None else rounds[:round_limit]


def _candidate_ids(conn, terms, rounds):
    """FTS5(3글자 이상)·LIKE(1~2글자) 로 낱말이 하나라도 든 문항 id 집합을 찾는다. 범위 밖 회차는 뺀다."""
    long_terms = [t for t in terms if len(t) >= 3]
    short_terms = [t for t in terms if len(t) < 3]
    ids = set()
    if long_terms:
        match = " OR ".join('"' + t.replace('"', '""') + '"' for t in long_terms)
        ids.update(r[0] for r in conn.execute(
            "SELECT question_id FROM theory_fts WHERE theory_fts MATCH ?", (match,)))
    for term in short_terms:
        ids.update(r[0] for r in conn.execute(
            "SELECT question_id FROM theory_fts WHERE content LIKE ?", (f"%{term}%",)))
    in_scope = {r[0] for r in conn.execute(
        f"SELECT id FROM questions WHERE round IN ({','.join('?' * len(rounds))})", rounds)} if rounds else set()
    return ids & in_scope


def _doc_frequency(conn, term, rounds):
    """범위 안에서 낱말이 든 문항 수(희귀도 계산용)."""
    marks = ",".join("?" * len(rounds))
    return conn.execute(
        f"""SELECT COUNT(*) FROM theory_fts f JOIN questions q ON q.id = f.question_id
            WHERE q.round IN ({marks}) AND f.content LIKE ?""", [*rounds, f"%{term}%"]).fetchone()[0]


def _score_rows(conn, weights, ids, rounds):
    """후보 문항에 낱말 희귀도(idf) 가중 점수를 매겨 (점수, 행, 맞은 낱말) 을 점수 내림차순·최근 회차 순으로 돌려준다."""
    total = conn.execute(
        f"SELECT COUNT(*) FROM questions WHERE round IN ({','.join('?' * len(rounds))})", rounds).fetchone()[0]
    freq = {t: _doc_frequency(conn, t, rounds) for t in weights}
    idf = {t: math.log((total + 1) / (freq[t] + 1)) * (COMMON_DAMP if freq[t] > COMMON_DF_RATIO * total else 1.0)
           for t in weights}
    scored = []
    for qid in ids:
        row = conn.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()
        content = " ".join([row["question"], *json.loads(row["choices"]), row["explanation"]])
        matched = [t for t in weights if t in content]
        score = sum(weights[t] * idf[t] * (STEM_BONUS if t in row["question"] else 1) for t in matched)
        scored.append((score, row, matched))
    scored.sort(key=lambda s: (-s[0], -s[1]["round"], s[1]["number"]))
    return scored


def search_theory(query, conn, round_limit=DEFAULT_ROUNDS, entries=None, limit=RESULT_LIMIT):
    """질문과 관련된 이론 기출을 점수 순으로 찾는다.

    돌려주는 값: {"results": [...], "terms": 쓴 낱말, "expanded": 일상어에서 넓힌 공식 용어, "scope": 범위 설명, "note": 안내}
    각 결과: id, round, number, subject, tax, unit, question, matched(맞은 낱말), score, tax_notice(세무회계만).
    점수가 같으면 최근 회차가 위에 온다(정렬은 _score_rows).
    """
    entries = load_glossary() if entries is None else entries
    weights = build_weighted_terms(query, entries)
    rounds = scope_rounds(conn, round_limit)
    scope = "전체 회차" if round_limit is None else f"최신 {len(rounds)}회분"
    out = {"results": [], "terms": list(weights), "expanded": expand_everyday_words(query, entries),
           "scope": scope, "note": None}
    if not weights:
        out["note"] = "검색어로 쓸 수 있는 낱말(2글자 이상)이 없습니다."
        return out
    ids = _candidate_ids(conn, list(weights), rounds)
    scored = _score_rows(conn, weights, ids, rounds)
    scored = [s for s in scored if s[0] >= TAIL_CUT * scored[0][0]]
    for score, row, matched in scored[:limit]:
        out["results"].append({
            "id": row["id"], "round": row["round"], "number": row["number"], "subject": row["subject"],
            "tax": row["tax"], "unit": row["unit"], "question": row["question"],
            "matched": matched, "score": round(score, 2),
            "tax_notice": tax_notice(row["subject"], row["round"])})
    if not out["results"]:
        out["note"] = f"{scope}에서 관련 이론 기출을 찾지 못했습니다."
    return out
