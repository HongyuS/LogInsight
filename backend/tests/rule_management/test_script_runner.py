"""script_runner 子进程契约: 正常命中 / 缺 check / 缺文件 / 路径穿越 / 返回类型非法.

以真实子进程方式调用, 与 Worker 运行时路径一致。
"""
import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]  # tests/diagnosis/ -> backend/
RUNNER = BACKEND / "app" / "modules" / "diagnosis" / "script_runner.py"
SCRIPTS_DIR = BACKEND / "rules_scripts"


def _run(script_root, script_path, ctx):
    payload = {"script_root": str(script_root), "script_path": script_path, "ctx": ctx}
    proc = subprocess.run([sys.executable, "-I", str(RUNNER)],
                          input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.returncode, json.loads(proc.stdout.decode("utf-8"))


def _ctx(entries=None, rule_params=None):
    return {"rule": {"id": 1, "name": "t", "severity": "warn", "params": rule_params or {}},
            "task": {}, "entries": entries or [], "metrics": [], "file_stats": {},
            "meta": {"total_entries": len(entries or []), "total_metrics": 0, "truncated": False}}


def _oom_entries():
    return [{"line_no": i + 1, "raw": f"Jan  1 12:00:{s:02d} kernel: Out of memory: killed {i}",
             "ts": f"2026-10-10T12:00:{s:02d}+08:00", "level": "error",
             "component": "kernel", "file": "syslog", "fields": {}}
            for i, s in enumerate([0, 10, 20, 25])]


def test_oom_burst_hit():
    rc, out = _run(SCRIPTS_DIR, "oom_burst.py",
                   _ctx(_oom_entries(), {"window_seconds": 60, "threshold": 3,
                                         "keyword": "Out of memory"}))
    assert rc == 0 and out["ok"] is True
    findings = out["result"]["findings"]
    assert len(findings) == 1
    assert findings[0]["line_no"] == 4
    assert "4 次 OOM" in findings[0]["message"]
    assert out["result"]["logs"]


def test_missing_check(tmp_path):
    (tmp_path / "bad.py").write_text("def notcheck(ctx):\n    return {}\n", encoding="utf-8")
    rc, out = _run(tmp_path, "bad.py", _ctx())
    assert rc == 1 and out["ok"] is False
    assert "check(ctx)" in out["error"]


def test_missing_file(tmp_path):
    rc, out = _run(tmp_path, "nope.py", _ctx())
    assert rc == 1 and out["ok"] is False
    assert "不存在" in out["error"]


def test_path_traversal(tmp_path):
    rc, out = _run(tmp_path, "../secret.py", _ctx())
    assert rc == 1 and out["ok"] is False
    assert "逃逸" in out["error"]


def test_non_dict_return(tmp_path):
    (tmp_path / "list.py").write_text("def check(ctx):\n    return []\n", encoding="utf-8")
    rc, out = _run(tmp_path, "list.py", _ctx())
    assert rc == 1 and out["ok"] is False
    assert "dict" in out["error"]


def test_none_return_is_empty(tmp_path):
    (tmp_path / "none.py").write_text("def check(ctx):\n    return None\n", encoding="utf-8")
    rc, out = _run(tmp_path, "none.py", _ctx())
    assert rc == 0 and out["ok"] is True
    assert out["result"] == {"findings": [], "logs": []}