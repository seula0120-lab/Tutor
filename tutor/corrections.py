"""data/corrections.json 의 정정을 문제은행 문항에 덧씌운다. bank JSON 원본 파일은 고치지 않는다.

각 정정: {"id": "120-9", "field": "question|explanation|choices[0..3]", "before": 원문 일부, "after": 바꾼 글, "reason": 근거}.
- before 가 해당 칸에 정확히 한 번 나와야 한다. 아니면 오류(원본이 바뀌었는데 정정이 낡은 것).
- id 의 문항이 이번에 읽은 문항에 없으면(일부 회차만 읽는 경우) 건너뛴다.
"""
import json
import re
from pathlib import Path

CORRECTIONS_PATH = Path(__file__).resolve().parent.parent / "data" / "corrections.json"
_CHOICE = re.compile(r"choices\[(\d+)\]$")


def load_corrections(path=CORRECTIONS_PATH):
    path = Path(path)
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _replace_once(text, entry):
    before, after = entry["before"], entry["after"]
    if text.count(before) != 1:
        raise ValueError(f"정정 {entry['id']} {entry['field']}: before 가 {text.count(before)}번 나옴 → {before!r}")
    return text.replace(before, after, 1)


def apply_corrections(rounds, corrections):
    """rounds: [(회차, 문항 목록)]. 정정을 적용한 새 목록을 돌려준다(입력은 고치지 않는다)."""
    by_id = {}
    for entry in corrections:
        by_id.setdefault(entry["id"], []).append(entry)
    result = []
    for round_no, items in rounds:
        fixed = []
        for item in items:
            entries = by_id.get(f"{round_no}-{int(item['number'])}")
            if entries:
                item = {**item, "choices": list(item["choices"])}
                for entry in entries:
                    field = entry["field"]
                    match = _CHOICE.match(field)
                    if match:
                        i = int(match.group(1))
                        item["choices"][i] = _replace_once(item["choices"][i], entry)
                    elif field in ("question", "explanation"):
                        item[field] = _replace_once(item.get(field) or "", entry)
                    else:
                        raise ValueError(f"정정 {entry['id']}: 알 수 없는 칸 {field}")
            fixed.append(item)
        result.append((round_no, fixed))
    return result
