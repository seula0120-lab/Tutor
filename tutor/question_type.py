"""문제 글(질문 문장·보기)로 문항 유형을 판별한다. 낱말 규칙이라 틀릴 수 있다.

유형
- NEGATIVE(옳지 않은/틀린/아닌 것): 정답 보기 = 틀린 문장, 나머지 = 맞는 문장
- POSITIVE(옳은/맞는 것):           정답 보기 = 맞는 문장, 나머지 = 틀린 문장
- COMBINATION(조합형): '모두 고른', '짝지어진', '몇 개' 처럼 보기를 조합해 답하는 문제 → 문장 요약에서 뺀다
- CALCULATION(계산형): 금액·수량을 구하라는 물음이거나 보기가 전부 숫자인 문제 → 요약에서 뺀다
- IDENTIFY(식별형): '옳은/옳지 않은' 표현 없이 보기가 짧은 명사구(문장이 아님)인 문제 → 보기를 '맞는/틀린 문장'으로 쓸 수 없어 요약에서 빼고 목록에만 둔다
- UNKNOWN: 어느 쪽인지 규칙으로 못 가린 문제 → 요약에서 뺀다(틀린 문장을 맞다고 하지 않으려는 안전장치)

판별은 문제 글 전체가 아니라 **물음 부분(stem)** 으로 한다: 첫 '?' 또는 '…고르시오/구하시오' 까지의 글이다.
물음 안에서 '옳은'과 '옳지 않은'(또는 '잘못')이 함께 나오면 **물음 끝에 가장 가까운 표현**이 이긴다
(예: "잘못 회계처리한 경우 … 영향으로 옳은 것은?" 은 옳은 것).
판별 순서: 조합형 → 계산형 → 분명한 옳은/옳지 않은 표현(부정형·긍정형) → 식별형 → 약한 표현(긍정형) → 판별불가. ('옳은 것만 고른 것은' 은 '옳은 것' 을 포함하므로 조합형이 먼저다.)
"""
import re

NEGATIVE, POSITIVE = "부정형", "긍정형"
COMBINATION, CALCULATION, UNKNOWN = "조합형", "계산형", "판별불가"
IDENTIFY = "식별형"

# 물음이 실제로 금액·수량을 구하라는 표현. '금액은/금액을/산출' 처럼 글 속에 흔히 나오는 낱말은 넣지 않는다.
CALC_ASK = re.compile(r"얼마|구하(시오|여라|라|면)|계산(하면|하시오|하여라)|몇\s*(원|주|%|시간|단위|퍼센트)")
COMBO_STEM = re.compile(r"모두\s*(고른|고르|선택|골라)|(것|말)만\s*(고른|고르|선택|골라|짝)|짝지어|짝지은|짝\s*지|"
                        r"올바르게\s*나열|순서대로|조합")
COUNT_STEM = re.compile(r"몇\s*(개|가지)")      # '구하면 몇 개' 는 계산, '옳은 것은 몇 개' 는 조합이다
NEGATIVE_STEM = re.compile(r"(옳|맞|적절하|적합하|올바르|바르|타당하|해당하|해당되|일치하|가능하|인정되|허용되)"
                           r"(지|진)\s*(않|못)|틀린|틀리|아닌|잘못|부적절|않는\s*것|않은\s*것|없는\s*것|거리가\s*먼|"
                           r"수\s*없는|않아도\s*되는|미치지\s*않는|제외되는")
POSITIVE_STEM = re.compile(r"옳은|맞는|맞게|적절한|적합한|올바른|바른|타당한|옳게|일치하는|해당하는|해당되는|"
                           r"가능한|인정되는")
WEAK_POSITIVE_STEM = re.compile(r"설명으로|설명은|내용은|것은\?|것은$")   # 다른 표지가 하나도 없을 때만 쓴다
NUMERIC_CHOICE = re.compile(r"^[\s\d,.\-+%원주개월일년시간배()]+$")
# 보기가 '가, 다' / '㉠, ㉡' / 'ㄱ, ㄴ' 처럼 기호의 나열이면 조합형이다.
SYMBOL_CHOICE = re.compile(r"^(?:[가나다라마바사]|[㉠-㉧]|[ㄱ-ㅎ])(?:\s*[,·ㆍ와과및]\s*(?:[가나다라마바사]|[㉠-㉧]|[ㄱ-ㅎ]))*\s*$")
STEM_END = re.compile(r"[?？]|고르시오|구하시오|구하여라|계산하시오|하시오")
SENTENCE_END = re.compile(r"(다|요|음|함|임|됨)\s*\.?$|\.$")
# 판별불가가 될 뻔한 물음 중, 참·거짓 문장이 아니라 '항목 하나를 고르는' 물음이라고 안전하게 말할 수 있는 표현.
SELECT_STEM = re.compile(r"어느\s*(것|방법|쪽|경우)|어떻게|무엇인가|누구인가|나머지(와|보다)?\s*다른|다른\s*(것|항목|경우)|"
                         r"(경우|사람|사례|거래|항목|것)(은|는)\s*[?？]")
TABLE_TAIL_MAX = 60        # 물음 뒤에 붙은 표 머리글(열 이름, 숫자 없음)의 최대 글자 수
NOUN_PHRASE_MAX = 30       # 이 글자 수 이하이고 문장 끝맺음이 없으면 명사구


def stem_of(question):
    """물음 부분: 첫 '?' 또는 '…고르시오/구하시오' 까지(그 표지 포함). 표지가 없으면 글 전체."""
    m = STEM_END.search(question)
    return question[:m.end()] if m else question


def strong_polarity(question):
    """물음에 '옳은/옳지 않은/틀린' 같은 분명한 표현이 있으면, 물음 끝에 가장 가까운 것으로 NEGATIVE / POSITIVE. 없으면 None."""
    stem = stem_of(question)
    neg = [m.end() for m in NEGATIVE_STEM.finditer(stem)]
    pos = [m.end() for m in POSITIVE_STEM.finditer(stem)]
    if not (neg or pos):
        return None
    return NEGATIVE if max(neg, default=-1) > max(pos, default=-1) else POSITIVE


def stem_polarity(question):
    """strong_polarity, 없으면 '설명으로/것은?' 같은 약한 표현으로 POSITIVE, 그래도 없으면 None."""
    return strong_polarity(question) or (POSITIVE if WEAK_POSITIVE_STEM.search(stem_of(question)) else None)


def is_noun_phrase_choices(choices):
    return bool(choices) and all(len(c.strip()) <= NOUN_PHRASE_MAX and not SENTENCE_END.search(c.strip()) for c in choices)


def classify(question, choices):
    """문제 글과 보기로 유형 상수를 돌려준다."""
    stem = stem_of(question)
    if COMBO_STEM.search(stem) or (choices and all(SYMBOL_CHOICE.match(c) for c in choices)):
        return COMBINATION
    if CALC_ASK.search(stem):
        return CALCULATION
    if COUNT_STEM.search(stem):
        return COMBINATION
    if choices and all(NUMERIC_CHOICE.match(c) for c in choices):
        return CALCULATION
    strong = strong_polarity(question)
    if strong:
        return strong                      # 옳은/옳지 않은 것을 고르라는 분명한 물음이면 보기가 짧아도 문장 요약 대상이다
    if is_noun_phrase_choices(choices):
        return IDENTIFY                    # '무엇인가/어느 것인가' 처럼 항목 하나를 고르는 물음
    return stem_polarity(question) or _select_one(question, choices) or UNKNOWN


def _select_one(question, choices):
    """다른 표지가 없을 때만: 항목 하나를 고르는 물음이면 IDENTIFY, 아니면 None.

    ① '어느 것/어떻게/누구인가/나머지와 다른 것' 같은 물음, ② 물음 뒤에 표 머리글(열 이름)만 붙고 보기가 짧은 값인 표 형식 문항.
    자료를 주고 금액·세무조정을 고르게 하는 문항처럼 이 둘에 안 맞는 것은 그대로 판별불가로 둔다."""
    stem = stem_of(question)
    if SELECT_STEM.search(stem):
        return IDENTIFY
    tail = question[len(stem):].strip()
    if tail and len(tail) <= TABLE_TAIL_MAX and not re.search(r"\d", tail) and not SENTENCE_END.search(tail) and all(len(c.strip()) <= NOUN_PHRASE_MAX for c in choices):
        return IDENTIFY
    return None
