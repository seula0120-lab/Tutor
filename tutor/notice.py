"""세법 개정 확인 표시. 세무회계(부가가치세·소득세·법인세) 문항에만 붙고 재무·원가 문항에는 붙지 않는다.

세법은 해마다 바뀌어서, 옛 회차의 정답이 현재 규정과 다를 수 있다. 그래서 회차를 함께 적어 알린다.
"""
TAX_SUBJECT = "세무회계"


def tax_notice(subject, round_no):
    """세무회계면 '128회 · 세법 개정 확인 필요', 아니면 None."""
    return f"{round_no}회 · 세법 개정 확인 필요" if subject == TAX_SUBJECT else None
