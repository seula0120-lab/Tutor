"""data/bank/<회차>.json 의 이론 문항을 읽어 태그를 붙이고 DB 에 적재한다.

적재는 '비우고 다시 채우기'다. questions 와 색인을 같은 트랜잭션에서 함께 지우고 채우므로
몇 번을 돌려도 문항 수와 색인 줄 수가 같다(색인 중복이 생기지 않는다).
"""
import json
from pathlib import Path

from .tagging import tag_question

BANK_DIR = Path(__file__).resolve().parent.parent / "data" / "bank"


def read_bank_files(bank_dir=BANK_DIR):
    """회차 번호 순으로 정렬한 (회차, 이론 문항 목록) 을 돌려준다."""
    files = sorted(Path(bank_dir).glob("*.json"), key=lambda p: int(p.stem))
    rounds = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        rounds.append((int(data["round"]), data.get("theory", [])))
    return rounds


def question_row(round_no, item):
    """원본 문항 하나를 DB 행(dict)으로 바꾼다. 원본은 고치지 않는다."""
    number = int(item["number"])
    choices = list(item["choices"])
    explanation = item.get("explanation") or ""
    subject, tax, unit = tag_question(number, item["question"], choices, explanation)
    return {
        "id": f"{round_no}-{number}", "round": round_no, "number": number,
        "subject": subject, "tax": tax, "unit": unit, "points": int(item.get("points") or 2),
        "question": item["question"], "choices": json.dumps(choices, ensure_ascii=False),
        "answer": str(item["answer"]), "explanation": explanation,
    }


def search_content(row):
    """검색 색인에 넣을 글: 질문 + 보기 + 해설."""
    return " ".join([row["question"], *json.loads(row["choices"]), row["explanation"]])


def load_bank(conn, rounds):
    """rounds 로 DB 를 통째로 다시 채우고 적재한 문항 수를 돌려준다."""
    rows = [question_row(round_no, item) for round_no, items in rounds for item in items]
    columns = list(rows[0]) if rows else []
    with conn:  # 하나의 트랜잭션
        conn.execute("DELETE FROM theory_fts")
        conn.execute("DELETE FROM questions")
        marks = ",".join("?" for _ in columns)
        conn.executemany(f"INSERT INTO questions({','.join(columns)}) VALUES ({marks})",
                         [[r[c] for c in columns] for r in rows])
        conn.executemany("INSERT INTO theory_fts(question_id, content) VALUES (?, ?)",
                         [(r["id"], search_content(r)) for r in rows])
    return len(rows)
