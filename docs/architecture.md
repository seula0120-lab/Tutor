# 구조 (architecture)

함수·파일 이름은 코드에서 확인한 실제 이름이다. 화살표 위 글은 넘기는 값이다.

## 1. 원본에서 화면까지 데이터 흐름

```mermaid
flowchart LR
    RAW["data/raw/&lt;회차&gt;/ 확정답안 PDF·HWP"] -->|find_answer_file<br/>read_answer_lines| LINES["줄 목록"]
    LINES -->|parse_theory<br/>정답표 대조 check_item| BANK["data/bank/&lt;회차&gt;.json<br/>이론 15문항"]
    FIX["data/corrections.json<br/>정정 목록"] -->|apply_corrections| READ
    BANK -->|read_bank_files| READ["정정 적용된 문항"]
    READ -->|load_bank<br/>question_row · tag_question<br/>search_content| DB[("data/tutor.db<br/>questions · theory_fts<br/>records · favorites ...")]
    DB --> API["tutor/web.py<br/>dispatch · ROUTES"]
    GLOSS["data/glossary.json<br/>용어 사전"] --> API
    TAX["data/tax_changes.json<br/>세법 개정 메모"] --> API
    API -->|JSON| UI["tutor/static<br/>index.html · toc.html<br/>glossary_review.html<br/>quizcard.js · theme.css"]
    DB -->|export_data · render_html| OFF["data/export/회계튜터_목차.html<br/>(오프라인 한 파일)"]
    SYNC["sync_raw<br/>(서버 시작·scripts/sync_raw.py)"] -.새·바뀐 원본만 변환.-> BANK
    SYNC -.전체 다시 적재.-> DB
```

새 회차는 `data/raw/<회차>/` 에 파일만 넣으면 서버 시작 때 `sync_raw` 가 변환하고(`needs_convert`) DB 를 다시 채운다. 정답표와 맞지 않는 회차는 적재하지 않고 이유를 보고한다.

## 2. 질문 하나가 처리되는 순서 (`POST /api/ask`)

```mermaid
sequenceDiagram
    participant U as 브라우저(index.html)
    participant W as web.dispatch → api_ask
    participant S as search.search_theory
    participant M as summary.build_summary
    participant A as ai.explain
    U->>W: {q, scope}
    W->>S: 질문·범위
    S->>S: expand_everyday_words (일상어→공식 용어)
    S->>S: _candidate_ids (FTS5·LIKE 후보)
    S->>S: _score_rows (희귀도 점수, 흔한 낱말 감점)
    S->>S: TAIL_CUT 아래 꼬리 제거, tax_notice 붙임
    S-->>W: results · terms
    W->>M: results · terms
    M->>M: related_results (관련 기출만)
    M->>M: classify (옳은/옳지 않은/계산/조합/식별형)
    M->>M: split_sentences → merge_sentences (같은 뜻 합침)
    M->>M: select_sentences · coverage
    M-->>W: 요약 카드(맞는 문장·함정·제외 문항)
    W->>W: covers_core_terms (직접 기출 없음 안내 여부)
    W->>A: query · summary
    A-->>W: AI 설명 또는 상태 메시지 (키 없음·실패여도 앞의 결과는 그대로)
    W-->>U: search · summary · no_direct · ai
    U->>U: renderSummary · highlight (핵심어 형광펜)
```

풀이 쪽은 `api_answer` → `quiz.check_answer`(채점, 정답은 서버만 안다) → `records.save`(풀이 기록) 순이다. 모의고사는 `mock.pick_exam` → `mock.grade`.

## 3. 파일 역할 관계도

```mermaid
flowchart TB
    subgraph 입력["입력·변환"]
        answer_lines["answer_lines.py<br/>PDF·HWP 읽기"] --> answer_parser["answer_parser.py<br/>문항 나누기·정답표 대조"]
        sync["sync.py<br/>새 회차 자동 반영"] --> answer_parser
        corrections["corrections.py<br/>정정 적용"] --> bank
        tagging["tagging.py<br/>과목·세목·단원 태그"] --> bank["bank.py<br/>DB 적재"]
        sync --> bank
    end
    bank --> db["db.py<br/>스키마·connect"]
    subgraph 검색·요약["검색·요약"]
        glossary["glossary.py<br/>일상어 확장·용어 주석"] --> search["search.py<br/>FTS5 검색·점수"]
        search --> summary["summary.py<br/>요약 카드"]
        question_type["question_type.py<br/>문항 유형"] --> summary
        notice["notice.py<br/>세법 개정 표시"] --> search
        notice --> summary
        summary --> ai["ai.py<br/>Claude 설명·출처 검증"]
    end
    subgraph 학습["학습 기능"]
        quiz["quiz.py<br/>문제·채점"] --> records["records.py<br/>풀이 기록·오답노트"]
        mock["mock.py<br/>모의고사"] --> records
        analysis["analysis.py<br/>문제 분석·공부 순서"] --> records
        toc["toc.py<br/>목차"]
        favorites["favorites.py<br/>즐겨찾기"]
        glossary_review["glossary_review.py<br/>용어 사전 검토"]
    end
    db --> search
    db --> quiz
    web["web.py<br/>ROUTES·PAGES·정적 파일"] --> search
    web --> summary
    web --> ai
    web --> quiz
    web --> mock
    web --> analysis
    web --> toc
    web --> favorites
    web --> glossary_review
    web --> static["static/<br/>HTML·quizcard.js·theme.css·fonts"]
    export["export.py<br/>오프라인 한 파일"] --> toc
    export --> quiz
    scripts["scripts/<br/>load_db · sync_raw · eval_search<br/>export_offline · verify · check_ui.mjs"] -.사용.-> bank
    scripts -.사용.-> search
    scripts -.사용.-> export
```

규칙: 화면(`static/`)은 서버 JSON 만 보고, 정답·해설은 `quiz`·`mock` 이 채점한 뒤에만 내려보낸다. 검색 점수와 요약 규칙은 `search.py`·`summary.py` 한 곳에 있다.
