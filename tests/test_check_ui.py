import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_check_ui_script_is_valid_and_uses_no_extra_packages():
    script = ROOT / "scripts" / "check_ui.mjs"
    assert subprocess.run(["node", "--check", str(script)], capture_output=True).returncode == 0
    text = script.read_text(encoding="utf-8")
    assert "--headless=new" in text and "--remote-debugging-port" in text and "new WebSocket" in text
    imports = [line for line in text.splitlines() if line.startswith("import ")]
    assert all('"node:' in line for line in imports)               # 내장 모듈만


def test_verify_lists_ui_check_as_manual_and_screens_are_ignored():
    assert "미실행(수동)" in (ROOT / "scripts" / "verify.py").read_text(encoding="utf-8")
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert "scratch/" in ignored and "data/export/" in ignored
