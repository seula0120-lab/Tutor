#!/bin/zsh
# 회계튜터 실행: 이 파일이 있는 폴더를 프로젝트 폴더로 쓴다(경로를 박지 않음).
# 이미 떠 있으면 브라우저만 열고, 아니면 서버를 켜고 연다. 이 창을 닫으면(또는 Ctrl+C) 서버도 끝난다.

PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR" || exit 1

PY="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "가상환경이 없습니다. README.md 의 '설치'를 먼저 하세요."
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  read -r "?엔터를 누르면 닫힙니다."
  exit 1
fi

# 8000~8010 중에서 회계튜터가 떠 있는 포트를 찾고, 없으면 처음 비어 있는 포트를 쓴다.
PORT=""
for p in {8000..8010}; do
  URL="http://127.0.0.1:$p/"
  if curl -fsS -o /dev/null "${URL}toc" 2>/dev/null; then
    open "$URL"
    exit 0
  fi
  curl -sS -o /dev/null --max-time 2 "$URL" 2>/dev/null
  if [[ $? -eq 7 && -z "$PORT" ]]; then PORT=$p; fi   # 7 = 연결 거부 = 비어 있음
done
if [[ -z "$PORT" ]]; then
  echo "8000~8010 포트가 모두 다른 프로그램에 쓰이고 있습니다."
  read -r "?엔터를 누르면 닫힙니다."
  exit 1
fi
URL="http://127.0.0.1:$PORT/"

clear
echo "회계튜터를 시작합니다... ($URL)"
echo "이 창을 닫으면 서버도 종료됩니다."
echo "처음이면 열린 화면에서 관리자 계정을 만드세요(기존 기록은 이 계정이 이어받습니다)."
echo "다른 사람 계정은 로그인 뒤 위쪽 '계정 관리'에서 만듭니다."
"$PY" -m tutor.web --port "$PORT" &
SERVER_PID=$!

cleanup() { kill "$SERVER_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM HUP

for _ in {1..50}; do
  if curl -fsS -o /dev/null "${URL}toc" 2>/dev/null; then
    open "$URL"
    break
  fi
  sleep 0.2
done

wait "$SERVER_PID"
