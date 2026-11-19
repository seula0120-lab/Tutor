"""회계·세법 용어 사전(data/glossary.json)을 읽고, 일상어 동의어 확장과 본문 주석에 쓴다.

사전 항목: {"term": 공식 용어, "meaning": 쉬운 풀이, "synonyms": [일상어 문구, ...]}.
사전은 읽기 보조용이며 시험 판단 근거가 아니다(공식 해설이 근거).
"""
import json
import re
from pathlib import Path

GLOSSARY_PATH = Path(__file__).resolve().parent.parent / "data" / "glossary.json"


def load_glossary(path=GLOSSARY_PATH):
    """사전 파일을 읽어 항목 목록을 돌려준다. 용어·뜻이 글자가 아닌 줄은 버린다. 파일이 없으면 빈 목록."""
    path = Path(path)
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = []
    for item in data.get("terms", []):
        if isinstance(item.get("term"), str) and isinstance(item.get("meaning"), str):
            synonyms = [s for s in item.get("synonyms") or [] if isinstance(s, str)]
            entries.append({"term": item["term"], "meaning": item["meaning"], "synonyms": synonyms})
    return entries


def _compact(text):
    """띄어쓰기 차이를 무시하려고 공백을 모두 뺀다."""
    return re.sub(r"\s+", "", text)


def expand_everyday_words(query, entries):
    """질문 속 일상어(synonyms)에 해당하는 공식 용어 목록을 사전 순서대로 돌려준다."""
    compact_query = _compact(query)
    found = []
    for entry in entries:
        if any(_compact(s) in compact_query for s in entry["synonyms"] if s.strip()):
            found.append(entry["term"])
    return found


def annotate(text, entries):
    """글을 [{"text": 조각, "term": 용어 또는 None}] 조각 목록으로 나눈다(용어 부분에 term 을 단다).

    긴 용어를 먼저 찾고 서로 겹치는 곳은 먼저 잡은 쪽을 쓴다(예: '비정상공손' 안의 '공손' 은 따로 달지 않음).
    """
    spans = []
    taken = [False] * len(text)
    for term in sorted({e["term"] for e in entries}, key=len, reverse=True):
        for match in re.finditer(re.escape(term), text):
            start, end = match.span()
            if not any(taken[start:end]):
                spans.append((start, end, term))
                taken[start:end] = [True] * (end - start)
    spans.sort()
    pieces, cursor = [], 0
    for start, end, term in spans:
        if start > cursor:
            pieces.append({"text": text[cursor:start], "term": None})
        pieces.append({"text": text[start:end], "term": term})
        cursor = end
    if cursor < len(text):
        pieces.append({"text": text[cursor:], "term": None})
    return pieces
