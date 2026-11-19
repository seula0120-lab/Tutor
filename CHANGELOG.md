# CHANGELOG

## v0.2 - 2026-11-19

### 바뀐 것
- 코드 점검(`docs/code_audit.md`): `dispatch` 를 `ROUTES` 표와 경로별 함수로 나눔, `apply_corrections` 분리.
- 검색 잡음 줄이기(`docs/search_noise.md`): 흔한 낱말 감점, 점수 낮은 꼬리 제거.
- 문장 합치기 점검(`docs/merge_audit.md`): 같은 문항 보기·숫자가 다른 문장·반대어가 엇갈린 문장은 합치지 않음.
- 요약 카드 판별불가 9문항 중 8문항을 식별형으로(`docs/summary_card_audit.md`).
- 데이터 정리(`docs/data_cleanup.md`): PDF 로 확인한 줄바꿈 띄어쓰기 14건 정정(정정 목록 42건), 중복 12쌍 전문 대조.
- 용어 사전 검토 화면 `/glossary-review`(검토 상태·메모는 `data/glossary_review.json` 에만 저장, `glossary.json` 불변).
- 디자인 개편: `theme.css` 토큰, Pretendard·Noto Serif KR 번들, 고정 상단 바·알약 탭, 시험지 카드·OMR, 모의고사 2단(모바일 하단 바), 요약 카드 노트(✔/✘·형광펜), 라이트/다크, 접근성. 오프라인 파일도 같은 스타일.
- 문서: `docs/architecture.md`(mermaid 3개), `docs/presentation_script.md`.

### 검증 결과
- 단위 테스트 231개 통과(`scripts/verify.py`).
- 검색 평가 15문항 hit@3: 14/15 → 14/15 (전체 회차, 변화 없음), 최신 10회분 15/15.
- 동결 평가셋 30문항 hit@3: 24/30 → 25/30 (떨어지지 않음).
- 화면 자동 점검 `node scripts/check_ui.mjs`: 17 통과 / 0 실패, 스크린샷 24장 `scratch/screens/design/`.
- 미검증: Claude 실제 호출·인용 일치(API 키 없음). 평가 질문은 AI 가 만들어 점수가 높게 나왔을 수 있다.

## v0.1-mvp — 2026-11-19

### 기능
- 문제은행: 이론 36회차 540문항, 과목·세목·단원 태그, 새 회차 자동 반영(`scripts/sync_raw.py`, 서버 시작 시).
- 검색(FTS5·LIKE + 동의어, 기본 전체 회차), 용어 주석, 요약 카드(맞는 문장·함정 문장·직접 기출 없음 안내), 선택적 Claude 설명.
- 학습: 퀴즈(오답 시 보기 잠금), 풀이 기록·오답노트, 모의고사(재무5·원가5·세무5), 공부 순서(정답률=문항별 최근 결과), 즐겨찾기·최근 질문, `/toc` 목차, 오프라인 목차 HTML(정답·해설·채점 포함), 세법 개정 표시.
- 품질: 요약 카드 유형 판별 개선(식별형, 전항 정답 처리), 단원 태그 재분류('기타' 제거, 법인세회계·금융·퇴직·기타소득 단원 유지), 원문 정정 목록 `data/corrections.json`(28건, 73-9 PDF 대조 포함), 빈 해설 '공식 해설 없음'.
- 도구: 화면 자동 점검 `scripts/check_ui.mjs`, 동결 평가셋 30문항, 실행 파일 `회계튜터 실행.command`.
- 문서: README, SPEC, PROGRESS, 점검 보고서 4종, 이전 프로젝트 비교, 단원 태그 변경 목록.

### 검증 결과
- 단위 테스트 198개 통과(`scripts/verify.py`).
- 검색 평가(기존 15문항): hit@3 14/15 = 93% (전체 회차), 최신 10회분 15/15.
- 동결 평가셋 30문항: hit@3 24/30 = 80% (처음 측정값과 같음, 검색 코드 변경 없음).
- 화면 자동 점검 `node scripts/check_ui.mjs`: 10 통과 / 0 실패(수동 실행).
- 새 가상환경에 `requirements.txt` 로 설치해 테스트 198개 통과 확인.
- 미검증: Claude 실제 호출·인용 일치(API 키 없음).

### 알려진 한계
- 이론만 다룬다. 세법 개정은 사람이 확인해야 한다(`exam_date`·`tax_changes.json` 비어 있음).
- 기출 원본(`data/raw`, `data/bank`)은 Git 제외. 오프라인 HTML 은 정답을 포함한다.
- 사람 검토 항목은 `PROGRESS.md` 참고.
