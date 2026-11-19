"""테스트용 가짜 확정답안 PDF 를 만든다(실제 기출 원본을 쓰지 않는다).

구성: 쪽마다 머리글, 첫 장 'A형' 정답표(15칸), 이론 1~15번(문제·보기 4개·[답]·해설), 그다음 '실','무' 표시.
2번 문항은 보기를 한 줄에 두 개씩(① ② / ③ ④) 적어 '한 줄 여러 보기' 해석도 함께 시험한다.
결함을 일부러 넣는 옵션으로 검사가 막는지 확인한다.
"""
import pymupdf

FONT = "korea"  # PyMuPDF 내장 한글 글꼴
PAGE_BOTTOM = 800


def default_answers():
    """정답 15개: 1,2,3,4 를 돌려 쓰고 3번만 복수정답 '1,3'."""
    answers = [str(i % 4 + 1) for i in range(15)]
    answers[2] = "1,3"
    return answers


def circled(answer):
    return ",".join("①②③④"[int(a) - 1] for a in answer.split(","))


class Writer:
    """줄을 위에서 아래로 쓰고, 쪽이 차면 새 쪽(머리글 포함)을 연다."""

    def __init__(self, doc, round_no):
        self.doc, self.round_no, self.page, self.y = doc, round_no, None, 0
        self.new_page()

    def new_page(self):
        self.page = self.doc.new_page()
        self.y = 40
        self.page.insert_text((50, 20), f"[제{self.round_no}회 전산세무1급 확정답안]", fontname=FONT, fontsize=9)

    def line(self, text, x=50):
        if self.y > PAGE_BOTTOM:
            self.new_page()
        self.page.insert_text((x, self.y), text, fontname=FONT, fontsize=10)
        self.y += 14


def make_answer_pdf(path, round_no, *, key=None, answers=None, questions=15, choices=4,
                    practice_marker=True, key_table=True):
    """가짜 확정답안 PDF 를 path 에 저장한다.

    key: 첫 장 정답표 값(기본은 answers 와 같게). answers: [답] 에 적을 정답. questions: 이론 문항 수.
    choices: 4번 문항의 보기 수(3 이면 보기 하나가 빠진 결함). practice_marker=False 면 '실무시험' 표시 없음.
    key_table=False 면 'A형' 정답표 없음.
    """
    answers = answers or default_answers()
    key = key or answers
    doc = pymupdf.open()
    w = Writer(doc, round_no)
    if key_table:
        w.line("A형")
        for cell in key:
            w.line(circled(cell))
    for n in range(1, questions + 1):
        w.line(f"{n}. 다음 중 개념{n}에 대한 설명으로 옳은 것은?")
        if n == 2:
            w.line(f"① 가{n}  ② 나{n}")
            w.line(f"③ 다{n}  ④ 라{n}")
        else:
            count = choices if n == 4 else 4
            for k in range(count):
                w.line(f"{'①②③④'[k]} 보기{n}-{k + 1}")
        w.line(f"[답] {circled(answers[(n - 1) % 15])} 공식 해설 {n}번 내용")
    if practice_marker:
        w.line("실")
        w.line("무")
        w.line("문제1 실무 문제 내용")
    doc.save(path)
    doc.close()
    return path
