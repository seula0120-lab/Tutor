import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "docs" / "presentation_script.md").read_text(encoding="utf-8")
CHECK_UI = (ROOT / "scripts" / "check_ui.mjs").read_text(encoding="utf-8")


def test_screenshots_named_in_script_are_produced_by_check_ui():
    screens = set(re.findall(r'^\s+"([^"]+)": async \(\) =>', CHECK_UI, re.M))
    for name in re.findall(r"`([^`]+)-(?:light|dark|mobile)\.png`", DOC):
        assert name in screens, name


def test_script_states_the_two_honesty_caveats_and_demo_questions():
    assert "AI(Claude)가 DB 원문을 읽고 만들었습니다" in DOC and "높게 나왔을 수 있습니다" in DOC
    assert "검증하지 못했습니다" in DOC
    assert DOC.count("**① ") == 1 and DOC.count("**② ") == 1 and DOC.count("**③ ") == 1


def test_numbers_in_script_match_current_unit_test_count():
    import subprocess, sys
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "--ignore=tests/test_presentation_doc.py"], cwd=ROOT, capture_output=True, text=True).stdout
    collected = int(re.search(r"(\d+) tests? collected", out).group(1))
    claimed = int(re.search(r"단위 테스트 \*\*(\d+)개", DOC).group(1))
    assert claimed <= collected                      # 대본이 실제보다 많은 테스트를 주장하지 않는다
