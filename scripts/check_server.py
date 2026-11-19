"""화면 자동 점검용 임시 서버: 실제 기출로 새 임시 DB(scratch/check.db)를 만들어 빈 포트에서 띄운다.
진짜 DB(data/tutor.db)는 건드리지 않고, API 키는 쓰지 않는다. 첫 줄에 'PORT <번호>'를 출력한다."""
import os
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["GLOSSARY_REVIEW_PATH"] = str(Path(__file__).resolve().parent.parent / "scratch" / "glossary_review.json")  # 진짜 파일을 건드리지 않는다

from tutor.bank import load_bank, read_bank_files  # noqa: E402
from tutor.db import ROOT, connect  # noqa: E402
from tutor.web import Handler  # noqa: E402


def main():
    """화면 점검용 임시 DB·임시 서버를 띄운다."""
    db = ROOT / "scratch" / "check.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.unlink(missing_ok=True)
    conn = connect(db)
    load_bank(conn, read_bank_files())
    conn.close()
    handler = type("CheckHandler", (Handler,), {"db_path": db})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    print(f"PORT {server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
