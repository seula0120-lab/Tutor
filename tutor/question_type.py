"""문제 글(질문 문장·보기)로 문항 유형을 판별한다. 낱말 규칙이라 틀릴 수 있다.

유형
- NEGATIVE(옳지 않은/틀린/아닌 것): 정답 보기 = 틀린 문장, 나머지 = 맞는 문장
- POSITIVE(옳은/맞는 것):           정답 보기 = 맞는 문장, 나머지 = 틀린 문장
- COMBINATION(조합형): '모두 고른', '짝지어진', '몇 개' 처럼 보기를 조합해 답하는 문제 → 문장 요약에서 뺀다
- CALCULATION(계산형): 금액·수량을 묻거나 보기가 전부 숫자인 문제 → 요약에서 뺀다
- UNKNOWN: 어느 쪽인지 규칙으로 못 가린 문제 → 요약에서 뺀다(틀린 문장을 맞다고 하지 않으려는 안전장치)
판별 순서: 계산형 → 조합형 → 부정형 → 긍정형. ('옳은 것만 고른 것은' 은 '옳은 것' 을 포함하므로 조합형이 먼저다.)
"""
import re

NEGATIVE, POSITIVE = "부정형", "긍정형"
COMBINATION, CALCULATION, UNKNOWN = "조합형", "계산형", "판별불가"

CALC_STEM = re.compile(r"얼마|계산하면|계산한|계산하시오|구하면|구하시오|산출|금액은|금액을|차이는|몇\s*(원|주|%|시간|단위)|몇\s*퍼센트")
COMBO_STEM = re.compile(r"모두\s*(고른|고르|선택|골라)|(것|말)만\s*(고른|고르|선택|골라|짝)|짝지어|짝지은|짝\s*지|"
                        r"몇\s*개|몇\s*가지|올바르게\s*나열|순서대로|조합")
NEGATIVE_STEM = re.compile(r"(옳|맞|적절하|적합하|올바르|바르|타당하|해당하|해당되|일치하|가능하|인정되|허용되)"
                           r"(지|진)\s*(않|못)|틀린|틀리|아닌|잘못|부적절|않는\s*것|않은\s*것|없는\s*것|거리가\s*먼")
POSITIVE_STEM = re.compile(r"옳은|맞는|맞게|적절한|적합한|올바른|바른|타당한|옳게|일치하는|해당하는|해당되는|"
                           r"가능한|인정되는|설명으로|설명은|내용은|것은\?|것은$")
NUMERIC_CHOICE = re.compile(r"^[\s\d,.\-+%원주개월일년시간배()]+$")
# 보기가 '가, 다' / '㉠, ㉡' / 'ㄱ, ㄴ' 처럼 기호의 나열이면 조합형이다.
SYMBOL_CHOICE = re.compile(r"^(?:[가나다라마바사]|[㉠-㉧]|[ㄱ-ㅎ])(?:\s*[,·ㆍ와과및]\s*(?:[가나다라마바사]|[㉠-㉧]|[ㄱ-ㅎ]))*\s*$")


def classify(question, choices):
    """문제 글과 보기로 유형 상수를 돌려준다."""
    if choices and all(NUMERIC_CHOICE.match(c) for c in choices):
        return CALCULATION
    if CALC_STEM.search(question):
        return CALCULATION
    if COMBO_STEM.search(question) or (choices and all(SYMBOL_CHOICE.match(c) for c in choices)):
        return COMBINATION
    if NEGATIVE_STEM.search(question):
        return NEGATIVE
    if POSITIVE_STEM.search(question):
        return POSITIVE
    return UNKNOWN
