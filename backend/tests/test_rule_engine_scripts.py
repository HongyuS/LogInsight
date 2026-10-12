"""RuleEngine.run_scripts: 命中/规范化/截断/超时/异常 (真实子进程, 无需 DB/Redis)."""
import asyncio
from pathlib import Path

from app.core.config import get_settings
from app.models.rule import MatchType, Rule, Severity
from app.modules.diagnosis.rule_engine import RuleEngine

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "rules_scripts"


def _rule(**kw):
    """构造脚本规则 (不经 DB), 缺省字段补齐."""
    base = dict(match_type=MatchType.script, pattern="", threshold={},
                script_params={}, script_timeout=5, severity=Severity.warn, priority=100)
    base.update(kw)
    return Rule(**base)


def _ctx(entries):
    return {"task": {"id": "t", "task_type": "diagnosis", "server_type": "linux"},
            "entries": entries, "metrics": [], "file_stats": {}}


def _oom_entries():
    return [{"line_no": i + 1, "raw": f"Jan  1 12:00:{s:02d} kernel: Out of memory: killed {i}",
             "ts": f"2026-10-10T12:00:{s:02d}+08:00", "level": "error",
             "component": "kernel", "file": "syslog", "fields": {}}
            for i, s in enumerate([0, 10, 20, 25])]


def test_oom_burst_hit_and_score(monkeypatch):
    monkeypatch.setattr(get_settings(), "RULE_SCRIPT_DIR", str(SCRIPTS_DIR))
    rule = _rule(id=1, name="OOM突发检测", severity=Severity.critical, script_path="oom_burst.py",
                 script_params={"window_seconds": 60, "threshold": 3, "keyword": "Out of memory"})
    out = asyncio.run(RuleEngine([rule]).run_scripts(_ctx(_oom_entries())))
    assert len(out.findings) == 1
    assert (out.findings[0].severity, out.findings[0].line_no) == ("critical", 4)
    assert out.errors == []
    assert out.durations[0]["rule_id"] == 1 and "seconds" in out.durations[0]
    assert out.logs and out.logs[0].startswith("[OOM突发检测]")
    assert RuleEngine.health_score(out.findings) == 90


def test_no_script_rules_is_noop(monkeypatch):
    monkeypatch.setattr(get_settings(), "RULE_SCRIPT_DIR", str(SCRIPTS_DIR))
    keyword_rule = Rule(id=2, name="kw", match_type=MatchType.keyword, pattern="x",
                        threshold={}, severity=Severity.info, priority=1)
    out = asyncio.run(RuleEngine([keyword_rule]).run_scripts(_ctx([])))
    assert out.findings == [] and out.errors == [] and out.durations == []


def test_timeout_killed(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "RULE_SCRIPT_DIR", str(tmp_path))
    (tmp_path / "slow.py").write_text(
        "import time\ndef check(ctx):\n    time.sleep(3)\n    return {'findings': []}\n", encoding="utf-8")
    out = asyncio.run(RuleEngine([_rule(id=2, name="慢脚本", script_path="slow.py",
                                        script_timeout=1)]).run_scripts(_ctx([])))
    assert out.findings == [] and len(out.errors) == 1
    assert "超时" in out.errors[0].error


def test_path_traversal_rejected(monkeypatch):
    monkeypatch.setattr(get_settings(), "RULE_SCRIPT_DIR", str(SCRIPTS_DIR))
    out = asyncio.run(RuleEngine([_rule(id=3, name="穿越",
                                        script_path="../app/main.py")]).run_scripts(_ctx([])))
    assert len(out.errors) == 1 and "逃逸" in out.errors[0].error


def test_error_isolated_per_rule(monkeypatch):
    """一条脚本失败不影响其他脚本规则执行 (并发隔离)."""
    monkeypatch.setattr(get_settings(), "RULE_SCRIPT_DIR", str(SCRIPTS_DIR))
    rules = [
        _rule(id=4, name="坏脚本", script_path="missing.py"),          # 文件不存在 → 失败
        _rule(id=5, name="OOM突发检测", severity=Severity.critical, script_path="oom_burst.py",
              script_params={"threshold": 3, "window_seconds": 60, "keyword": "Out of memory"}),
    ]
    out = asyncio.run(RuleEngine(rules).run_scripts(_ctx(_oom_entries())))
    assert len(out.findings) == 1 and len(out.errors) == 1
    assert out.errors[0].rule_name == "坏脚本"
    assert len(out.durations) == 2


def test_findings_normalized(monkeypatch, tmp_path):
    """message 覆盖 raw、severity 非法回退、line_no 越界兜底、非对象条目忽略."""
    monkeypatch.setattr(get_settings(), "RULE_SCRIPT_DIR", str(tmp_path))
    (tmp_path / "emit.py").write_text(
        "def check(ctx):\n"
        "    return {'findings': [\n"
        "        {'line_no': 2, 'message': '自定义说明', 'severity': 'bogus'},\n"
        "        'not a dict',\n"
        "        {'line_no': 999},\n"
        "    ], 'logs': ['hello']}\n", encoding="utf-8")
    entries = [{"line_no": i + 1, "raw": f"line-{i}", "ts": None, "level": "",
                "component": "", "file": "f", "fields": {}} for i in range(3)]
    out = asyncio.run(RuleEngine([_rule(id=6, name="规范化", script_path="emit.py")])
                      .run_scripts(_ctx(entries)))
    assert len(out.findings) == 2
    assert out.findings[0].raw == "自定义说明"          # message 覆盖
    assert out.findings[0].severity == "warn"            # 非法 severity 回退规则默认
    assert out.findings[1].line_no == 999
    assert "命中" in out.findings[1].raw                 # 越界无 raw → 兜底文案
    assert any("非对象" in log for log in out.logs)       # 非法条目被记录
    assert any("hello" in log for log in out.logs)


def test_findings_truncated(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "RULE_SCRIPT_DIR", str(tmp_path))
    monkeypatch.setattr(get_settings(), "SCRIPT_MAX_FINDINGS", 2)
    (tmp_path / "many.py").write_text(
        "def check(ctx):\n"
        "    return {'findings': [{'line_no': 1, 'message': str(i)} for i in range(5)]}\n",
        encoding="utf-8")
    out = asyncio.run(RuleEngine([_rule(id=7, name="截断", script_path="many.py")])
                      .run_scripts(_ctx([])))
    assert len(out.findings) == 2
    assert any("截断" in log for log in out.logs)