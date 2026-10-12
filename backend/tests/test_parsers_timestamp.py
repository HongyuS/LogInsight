"""通用文本解析器时间戳: parse_timestamp 两种格式 + GenericTextParser 回填验证."""
import asyncio
from datetime import datetime

from app.modules.diagnosis.parsers import GenericTextParser, parse_timestamp


def test_iso_space_separator():
    assert parse_timestamp("2026-10-10 12:00:00") == datetime(2026, 10, 10, 12, 0, 0)


def test_iso_millis_with_offset():
    got = parse_timestamp("2026-10-10T12:00:25.123+08:00")
    assert got is not None
    assert got.utcoffset() is not None
    assert (got.hour, got.minute, got.second) == (12, 0, 25)


def test_syslog_uses_current_year():
    got = parse_timestamp("Oct 10 12:00:30")
    assert got is not None
    assert (got.month, got.day, got.hour, got.minute, got.second) == (10, 10, 12, 0, 30)
    assert got.year == datetime.now().year


def test_invalid_returns_none():
    assert parse_timestamp("no timestamp here") is None
    assert parse_timestamp("") is None


def test_generic_parser_backfills_timestamp(tmp_path):
    log = tmp_path / "syslog.log"
    log.write_text("2026-10-10 12:00:00 kernel: Out of memory\n"
                   "plain line without ts\n", encoding="utf-8")
    result = asyncio.run(GenericTextParser().parse_file(log))
    assert result.entries[0].timestamp == datetime(2026, 10, 10, 12, 0, 0)
    assert result.entries[1].timestamp is None