"""data/raw/<회차>/ 의 확정답안 원본을 data/bank/<회차>.json 으로 바꾸고 DB 에 반영한다.

규칙
- 회차 번호는 폴더 이름(숫자)에서만 읽는다. 코드에 회차 번호를 적지 않는다.
- bank JSON 이 없거나 원본 파일이 더 새로울 때만 변환한다(변환은 느린 HWP 때문에 아끼는 목적).
- 검사(이론 15문항·보기 4개·정답표 일치)에 하나라도 걸리면 그 회차 JSON 을 쓰지 않는다. 이유는 결과에 담는다.
- DB 적재는 bank 전체로 '비우고 다시 채우기'라서 몇 번을 돌려도 결과가 같다.
"""
import json
import os
from pathlib import Path

from .answer_lines import find_answer_file, read_answer_lines
from .answer_parser import parse_theory
from .bank import BANK_DIR, load_bank, read_bank_files
from .db import ROOT

RAW_DIR = ROOT / "data" / "raw"

CONVERTED, UP_TO_DATE, FAILED = "변환", "최신", "실패"


def list_raw_rounds(raw_dir=RAW_DIR):
    """[(회차, 확정답안 파일)] 을 회차 순으로 돌려준다. 숫자 이름이 아닌 폴더·답안 없는 폴더는 건너뛴다."""
    raw_dir = Path(raw_dir)
    if not raw_dir.is_dir():
        return []
    found = []
    for folder in raw_dir.iterdir():
        answer = find_answer_file(folder) if folder.is_dir() and folder.name.isdigit() else None
        if answer:
            found.append((int(folder.name), answer))
    return sorted(found)


def needs_convert(answer_file, bank_file):
    """bank JSON 이 없거나, 원본이 JSON 보다 더 새로우면 True."""
    return not bank_file.is_file() or answer_file.stat().st_mtime > bank_file.stat().st_mtime


def write_json_atomically(path, data):
    """임시 파일에 쓴 뒤 바꿔 끼운다(쓰다 중단돼도 반쯤 쓴 JSON 이 남지 않는다)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temp, path)


def convert_round(round_no, answer_file, bank_dir):
    """한 회차를 변환해 bank JSON 을 쓴다. 결과: {"round", "status", "problems"}."""
    try:
        items, problems = parse_theory(round_no, read_answer_lines(answer_file))
    except Exception as err:  # 깨진 파일·변환 도구 실패도 그 회차만 건너뛰고 이유를 남긴다
        items, problems = [], [f"원본을 읽지 못했습니다: {type(err).__name__}: {err}"]
    if problems:
        return {"round": round_no, "status": FAILED, "problems": problems}
    bank = {"round": round_no, "source": f"data/raw/{round_no}/{answer_file.name}", "exam_date": None,
            "theory": items, "practice": [], "warnings": []}
    write_json_atomically(Path(bank_dir) / f"{round_no}.json", bank)
    return {"round": round_no, "status": CONVERTED, "problems": []}


def sync_raw(conn, raw_dir=RAW_DIR, bank_dir=BANK_DIR):
    """새·바뀐 원본만 변환하고 DB 를 bank 전체로 다시 채운다.

    돌려주는 값: {"rounds": [회차별 결과], "loaded": 적재한 문항 수}.
    """
    bank_dir = Path(bank_dir)
    results = []
    for round_no, answer_file in list_raw_rounds(raw_dir):
        if needs_convert(answer_file, bank_dir / f"{round_no}.json"):
            results.append(convert_round(round_no, answer_file, bank_dir))
        else:
            results.append({"round": round_no, "status": UP_TO_DATE, "problems": []})
    loaded = load_bank(conn, read_bank_files(bank_dir))
    return {"rounds": results, "loaded": loaded}


def format_report(report):
    """동기화 결과를 사람이 읽을 줄 목록으로 만든다."""
    lines = []
    for r in report["rounds"]:
        if r["status"] == FAILED:
            lines.append(f"[실패] {r['round']}회 적재 안 함:")
            lines.extend(f"   - {p}" for p in r["problems"])
        elif r["status"] == CONVERTED:
            lines.append(f"[변환] {r['round']}회")
    lines.append(f"DB 적재: 이론 {report['loaded']}문항 (원본 {len(report['rounds'])}회차 확인)")
    return lines
