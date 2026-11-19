from pdf_factory import default_answers, make_answer_pdf
from tutor.answer_lines import find_answer_file, read_answer_lines
from tutor.answer_parser import parse_theory, read_answer_key, read_answer_text, split_inline_markers


def parse(tmp_path, **options):
    path = make_answer_pdf(tmp_path / "answer.pdf", 901, **options)
    return parse_theory(901, read_answer_lines(path))


def test_good_pdf_gives_fifteen_complete_items(tmp_path):
    items, problems = parse(tmp_path)
    assert problems == [] and len(items) == 15
    first = items[0]
    assert first["id"] == "901-A-1" and first["round"] == 901 and first["number"] == 1
    assert first["question"] == "다음 중 개념1에 대한 설명으로 옳은 것은?"
    assert first["choices"] == ["보기1-1", "보기1-2", "보기1-3", "보기1-4"]
    assert first["answer"] == "1" and first["explanation"] == "공식 해설 1번 내용"
    assert [i["subject"] for i in items[::5]] == ["재무회계", "원가회계", "세무회계"]  # 번호로 과목 태그


def test_multiple_answer_and_inline_two_by_two_choices(tmp_path):
    items, problems = parse(tmp_path)
    assert items[2]["answer"] == "1,3"
    assert items[1]["choices"] == ["가2", "나2", "다2", "라2"]   # 한 줄 두 보기도 4개로 나뉨


def test_page_headers_do_not_leak_into_text(tmp_path):
    items, _ = parse(tmp_path)
    assert all("확정답안" not in i["explanation"] and "확정답안" not in " ".join(i["choices"]) for i in items)


def test_answer_key_mismatch_blocks_round_and_names_question(tmp_path):
    wrong_key = default_answers()
    wrong_key[6] = "4" if wrong_key[6] != "4" else "1"
    items, problems = parse(tmp_path, key=wrong_key)
    assert items == []                                   # 부분 적재 없이 전부 거부
    assert any(p.startswith("7번") and "정답 불일치" in p for p in problems)


def test_wrong_question_count_blocks_round(tmp_path):
    items, problems = parse(tmp_path, questions=14)
    assert items == [] and any("14개" in p for p in problems)


def test_missing_choice_blocks_round(tmp_path):
    items, problems = parse(tmp_path, choices=3)
    assert items == [] and any(p.startswith("4번") and "보기" in p for p in problems)


def test_missing_practice_marker_or_key_table_blocks_round(tmp_path):
    items, problems = parse(tmp_path, practice_marker=False)
    assert items == [] and any("실무시험" in p for p in problems)
    items, problems = parse(tmp_path, key_table=False)
    assert items == [] and any("정답표" in p for p in problems)


def test_answer_text_forms():
    assert read_answer_text("④ 해설") == ("4", " 해설")
    assert read_answer_text("복수정답 ②, ④")[0] == "2,4"
    assert read_answer_text("모두정답")[0] == "1,2,3,4"
    assert read_answer_text("해설만 있음")[0] is None


def test_answer_key_accepts_digit_cells():  # 옛 형식 정답표는 숫자로 적혀 있다
    lines = [{"text": t} for t in ["A형", "1", "2", "3,4", "B형", "4"]]
    assert read_answer_key(lines)[:3] == ["1", "2", "3,4"]


def test_split_inline_markers_keeps_single_leading_marker():
    line = {"page": 0, "x": 0, "x1": 100, "y": 0, "text": "① 가 ② 나"}
    assert [p["text"] for p in split_inline_markers(line)] == ["① 가", "② 나"]
    single = {"page": 0, "x": 0, "x1": 50, "y": 0, "text": "① 하나"}
    assert split_inline_markers(single) == [single]


def test_find_answer_file_prefers_pdf_then_hwp(tmp_path):
    assert find_answer_file(tmp_path) is None
    (tmp_path / "answer.hwp").write_bytes(b"x")
    assert find_answer_file(tmp_path).name == "answer.hwp"
    (tmp_path / "answer.pdf").write_bytes(b"x")
    assert find_answer_file(tmp_path).name == "answer.pdf"


def test_individual_costing_with_work_in_process_words_gets_individual_unit():
    from tutor.tagging import tag_question
    stem = "㈜우리상사는 정상개별원가 계산방법을 채택하고 있다. 배부차이를 조정하면 기말재공품의 가액은 얼마인가?"
    assert tag_question(8, stem, ["1", "2", "3", "4"], "")[2] == "개별원가계산"
    process = "다음 중 종합원가계산에서 기말재공품 평가에 대한 설명으로 옳은 것은?"
    assert tag_question(8, process, ["가", "나", "다", "라"], "")[2] == "종합원가계산"   # 종합원가 문항은 그대로


def test_cost_flow_and_general_cost_questions_go_to_cost_concepts():
    from tutor.tagging import tag_question
    c4 = ["1", "2", "3", "4"]
    flow = "다음의 자료를 이용하여 당기제품제조원가를 계산하시오. ㆍ제조간접비는 가공비의 30%이다."
    assert tag_question(8, flow, c4, "")[2] == "원가개념·분류"          # 자료에 제조간접비가 있어도 원가흐름 계산
    back = "자료에 기초하여 기초재공품 원가를 계산하면 얼마인가? ㆍ당기 변동제조간접비 : 5,000원"
    assert tag_question(8, back, c4, "")[2] == "원가개념·분류"
    general = "다음 중 원가회계에 대한 설명으로 틀린 것은? (나) 개별원가계산은 조선업에 적합하다."
    assert tag_question(8, general, c4, "")[2] == "원가개념·분류"


def test_explicit_process_or_job_costing_stem_keeps_its_unit():
    from tutor.tagging import tag_question
    c4 = ["1", "2", "3", "4"]
    process = "종합원가계산 하에서, 평균법에 의한 당기제품 제조원가가 다음과 같을 때 설명으로 올바른 것은?"
    assert tag_question(8, process, c4, "")[2] == "종합원가계산"
    job = "개별원가계산을 채택하고 있다. 당기총제조원가가 다음과 같을 때 직접재료원가는?"
    assert tag_question(8, job, c4, "")[2] == "개별원가계산"
