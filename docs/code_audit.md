# 코드 규칙 점검 (2026-11-19)

방법: `tutor/`, `scripts/` 의 모든 함수를 AST 로 훑어 길이(35줄 초과)·중첩(if/for/while/try/with 3단계 이상)·주석 없는 8줄 초과 함수를 뽑고, 원본 dict/list 를 직접 고치는 코드(`x["k"] = `, `.pop/.update/.extend/.insert/.sort()`)는 `grep` 으로 찾았다. 파일 역할 섞임은 눈으로 확인했다.

| 위치 | 문제 | 조치 |
|---|---|---|
| `web.py` `dispatch` | 65줄, 중첩 4단계, 주소 18개 처리와 오류 변환을 한 함수가 함 | **고침**: 주소별 처리 함수 + `ROUTES` 표 + 얇은 `dispatch`(오류 변환만). 응답 내용 동일 |
| `web.py` `do_GET` | 화면 주소마다 if 반복, 주석 없음 | **고침**: `PAGES` 표로 통일, 설명 추가 |
| `web.py` `main` | 주석 없음 | 설명 추가 |
| `corrections.py` `apply_corrections` | 중첩 6단계 | **고침**: `_apply_entry`(칸 하나), `_corrected`(복사 후 적용)로 분리. 입력은 복사해서 고침(테스트 있음) |
| `ai.py` `_call_claude` | 주석 없음 | 설명 추가 |
| `search.py` `_score_rows` | 주석 없음(핵심 점수 함수) | 설명 추가 |
| `notice.py` `_cached` | 주석 없음 | 설명 추가 |
| `scripts/*.py` `main` 4개 | 주석 없음 | 한 줄 설명 추가 |
| `answer_lines.py` `_read_pdf`, `handle_endtag` | 중첩 3단계 | 유지: 줄 단위 변환의 자연스러운 3단계이고 더 쪼개면 읽기 어려워짐. 테스트(`test_parser`)가 지킴 |
| `answer_parser.py` `split_blocks`, `glossary.py` `annotate`, `sync.py` `format_report` | 중첩 3단계 | 유지: 짧고(각 20줄 안팎) 한 가지 일만 함 |
| 원본 dict/list 직접 수정 | `summary.py`(75~79줄), `search.py`(127줄) 의 대입 | 유지: 둘 다 그 함수가 방금 만든 자기 dict 이다. 입력으로 받은 값을 고치는 곳은 없었음 |
| 파일 역할 섞임 | `web.py` 에 HTTP 처리와 `api_annotated/api_glossary/api_ask` 가 함께 있음 | 유지: 모두 요청→응답 변환 층이고 계산은 다른 모듈에 있음 |

동작은 바뀌지 않았다: 단위 테스트 198개가 그대로 통과한다.
