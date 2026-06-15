"""子进程脚本契约测试：不实际启动 playwright，验证环境变量处理。"""
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "sph_cookie_refresher.py"


def test_script_exists():
    assert SCRIPT.exists(), f"refresher script missing: {SCRIPT}"


def test_script_fails_without_env(monkeypatch, tmp_path):
    """缺 SPH_CALLBACK_URL 时应返回非 0 退出码。"""
    monkeypatch.setenv("PATH", str(tmp_path))  # 避免误启动
    r = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env={**os.environ, "SPH_CALLBACK_URL": "", "PATH": str(tmp_path)},
        capture_output=True,
        timeout=10,
    )
    assert r.returncode != 0
    assert b"SPH_CALLBACK_URL" in r.stderr or b"SPH_CALLBACK_URL" in r.stdout
