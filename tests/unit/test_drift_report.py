"""Tests for drift_report CLI module.

Covers all pure functions (is_drifted, severity_bucket, record_anchor_time,
aggregate_drift, render_text) and the run() end-to-end path via subprocess.

TDD: tests were written before implementation.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from claude_prospector.cli.drift_report import (
    EXIT_OK,
    aggregate_drift,
    is_drifted,
    load_variance_records,
    record_anchor_time,
    render_text,
    severity_bucket,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = timezone.utc


def _dt(year: int, month: int, day: int, hour: int = 0) -> datetime:
    """Build a UTC datetime."""
    return datetime(year, month, day, hour, tzinfo=_UTC)


def _make_record(
    *,
    session_id: str = "abc123",
    variance: str = "no variance",
    severity: int | None = 0,
    timestamp: str | None = None,
) -> dict:
    """Build a minimal variance record dict."""
    return {
        "session_id": session_id,
        "original_ask": None,
        "prior_asks": [],
        "actions": [],
        "variance": variance,
        "not_done": "",
        "severity": severity,
        "timestamp": timestamp,
    }


def _write_records(base_dir: Path, records: list[dict]) -> None:
    """Write records into <base_dir>/variance/<session_id>.json."""
    var_dir = base_dir / "variance"
    var_dir.mkdir(parents=True, exist_ok=True)
    for rec in records:
        path = var_dir / f"{rec['session_id']}.json"
        path.write_text(json.dumps(rec), encoding="utf-8")


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    """Run the drift-report subcommand as a subprocess."""
    return subprocess.run(
        [sys.executable, "-m", "claude_prospector", "drift-report", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# is_drifted — prose fallback (null-severity only)
# ---------------------------------------------------------------------------


class TestIsDrifted:
    """Tests for is_drifted() prose sentinel matching."""

    def test_no_variance_lowercase_is_clean(self) -> None:
        """'no variance' (canonical) is clean."""
        assert is_drifted("no variance") is False

    def test_no_variance_mixed_case_is_clean(self) -> None:
        """'No Variance' is clean (case-insensitive)."""
        assert is_drifted("No Variance") is False

    def test_no_variance_all_caps_is_clean(self) -> None:
        """'NO VARIANCE' is clean (case-insensitive)."""
        assert is_drifted("NO VARIANCE") is False

    def test_empty_string_is_clean(self) -> None:
        """Empty string is clean."""
        assert is_drifted("") is False

    def test_whitespace_only_is_clean(self) -> None:
        """Whitespace-only string (after strip) is clean."""
        assert is_drifted("   ") is False

    def test_prose_content_is_drifted(self) -> None:
        """Non-empty prose (not a sentinel) is drifted."""
        assert is_drifted("Added extra logging not in spec") is True

    def test_short_prose_is_drifted(self) -> None:
        """Single-word non-sentinel is drifted."""
        assert is_drifted("refactored") is True

    def test_no_variance_with_padding_is_clean(self) -> None:
        """'  no variance  ' (whitespace padded) is clean."""
        assert is_drifted("  no variance  ") is False

    def test_none_string_literal_is_drifted(self) -> None:
        """'none' (string) is NOT in sentinel set — it is drifted."""
        assert is_drifted("none") is True

    def test_na_string_is_drifted(self) -> None:
        """'n/a' is NOT in sentinel set — it is drifted."""
        assert is_drifted("n/a") is True


# ---------------------------------------------------------------------------
# severity_bucket
# ---------------------------------------------------------------------------


class TestSeverityBucket:
    """Tests for severity_bucket()."""

    def test_zero_maps_to_zero(self) -> None:
        assert severity_bucket(0) == "0"

    def test_one_maps_to_one(self) -> None:
        assert severity_bucket(1) == "1"

    def test_two_maps_to_two(self) -> None:
        assert severity_bucket(2) == "2"

    def test_three_maps_to_three(self) -> None:
        assert severity_bucket(3) == "3"

    def test_none_maps_to_null(self) -> None:
        assert severity_bucket(None) == "null"

    def test_missing_key_sentinel_maps_to_null(self) -> None:
        """Callers pass None for absent keys; verify null mapping."""
        assert severity_bucket(None) == "null"

    def test_out_of_range_positive_maps_to_null(self) -> None:
        assert severity_bucket(7) == "null"

    def test_out_of_range_negative_maps_to_null(self) -> None:
        assert severity_bucket(-1) == "null"

    def test_float_out_of_range_maps_to_null(self) -> None:
        """A float value (malformed) outside 0-3 maps to null."""
        assert severity_bucket(4.5) == "null"


# ---------------------------------------------------------------------------
# record_anchor_time
# ---------------------------------------------------------------------------


class TestRecordAnchorTime:
    """Tests for record_anchor_time()."""

    def test_uses_record_timestamp_when_present(self) -> None:
        """Record with ISO-8601 timestamp uses that value directly."""
        ts = "2026-05-20T10:00:00+00:00"
        rec = _make_record(timestamp=ts)
        mtime_float = 0.0  # should be ignored
        dt = record_anchor_time(rec, mtime_float)
        assert dt == datetime(2026, 5, 20, 10, 0, 0, tzinfo=_UTC)

    def test_falls_back_to_mtime_when_timestamp_absent(self) -> None:
        """Record without timestamp uses file mtime."""
        rec = _make_record(timestamp=None)
        # Use a known epoch — 2026-01-01 00:00:00 UTC
        mtime_float = datetime(2026, 1, 1, tzinfo=_UTC).timestamp()
        dt = record_anchor_time(rec, mtime_float)
        assert dt == datetime(2026, 1, 1, tzinfo=_UTC)

    def test_falls_back_to_mtime_when_timestamp_key_absent(self) -> None:
        """Record dict with no 'timestamp' key uses mtime fallback."""
        rec = {
            "session_id": "x",
            "variance": "no variance",
            "severity": 0,
        }
        mtime_float = datetime(2026, 3, 15, tzinfo=_UTC).timestamp()
        dt = record_anchor_time(rec, mtime_float)
        assert dt == datetime(2026, 3, 15, tzinfo=_UTC)

    def test_result_is_utc_aware(self) -> None:
        """Returned datetime is always tz-aware UTC."""
        ts = "2026-04-10T08:30:00+00:00"
        rec = _make_record(timestamp=ts)
        dt = record_anchor_time(rec, 0.0)
        assert dt.tzinfo is not None
        assert dt.utcoffset() == timedelta(0)


# ---------------------------------------------------------------------------
# aggregate_drift — pure function
# ---------------------------------------------------------------------------


class TestAggregateDrift:
    """Tests for aggregate_drift()."""

    def test_empty_records_returns_zero_rate(self) -> None:
        """Zero records in window → drift_rate 0.0, no division-by-zero."""
        from_dt = _dt(2026, 5, 26)
        to_dt = _dt(2026, 6, 2)
        result = aggregate_drift([], from_dt, to_dt)

        assert result["total_records"] == 0
        assert result["drift"]["drifted"] == 0
        assert result["drift"]["clean"] == 0
        assert result["drift"]["drift_rate"] == 0.0

    def test_empty_records_all_severity_buckets_present(self) -> None:
        """Even with no records, all 5 severity keys are present and 0."""
        from_dt = _dt(2026, 5, 26)
        to_dt = _dt(2026, 6, 2)
        result = aggregate_drift([], from_dt, to_dt)
        dist = result["severity_distribution"]
        assert set(dist.keys()) == {"0", "1", "2", "3", "null"}
        assert all(v == 0 for v in dist.values())

    def test_empty_records_trend_includes_all_days(self) -> None:
        """Trend spans [from, to) calendar days even with zero records."""
        from_dt = _dt(2026, 5, 26)
        to_dt = _dt(2026, 5, 28)  # 2 days: May 26, May 27
        result = aggregate_drift([], from_dt, to_dt)
        dates = [entry["date"] for entry in result["trend"]]
        assert dates == ["2026-05-26", "2026-05-27"]

    def test_empty_records_trend_zero_day_filling(self) -> None:
        """Zero-record days in trend have total=0, drifted=0, drift_rate=0."""
        from_dt = _dt(2026, 5, 26)
        to_dt = _dt(2026, 5, 28)
        result = aggregate_drift([], from_dt, to_dt)
        for entry in result["trend"]:
            assert entry["total"] == 0
            assert entry["drifted"] == 0
            assert entry["drift_rate"] == 0.0

    def test_severity_primary_zero_is_clean(self) -> None:
        """severity=0 → clean regardless of variance prose."""
        ts = "2026-05-27T12:00:00+00:00"
        rec = _make_record(
            session_id="s1",
            variance="some drift prose",  # would be drifted by prose
            severity=0,
            timestamp=ts,
        )
        from_dt = _dt(2026, 5, 26)
        to_dt = _dt(2026, 5, 29)
        result = aggregate_drift([rec], from_dt, to_dt)
        assert result["drift"]["drifted"] == 0
        assert result["drift"]["clean"] == 1

    def test_severity_primary_one_is_drifted(self) -> None:
        """severity=1 → drifted regardless of variance prose."""
        ts = "2026-05-27T12:00:00+00:00"
        rec = _make_record(
            session_id="s1",
            variance="no variance",  # would be clean by prose
            severity=1,
            timestamp=ts,
        )
        from_dt = _dt(2026, 5, 26)
        to_dt = _dt(2026, 5, 29)
        result = aggregate_drift([rec], from_dt, to_dt)
        assert result["drift"]["drifted"] == 1
        assert result["drift"]["clean"] == 0

    def test_severity_primary_two_is_drifted(self) -> None:
        """severity=2 → drifted."""
        ts = "2026-05-27T12:00:00+00:00"
        rec = _make_record(session_id="s1", severity=2, timestamp=ts)
        result = aggregate_drift([rec], _dt(2026, 5, 26), _dt(2026, 5, 29))
        assert result["drift"]["drifted"] == 1

    def test_severity_primary_three_is_drifted(self) -> None:
        """severity=3 → drifted."""
        ts = "2026-05-27T12:00:00+00:00"
        rec = _make_record(session_id="s1", severity=3, timestamp=ts)
        result = aggregate_drift([rec], _dt(2026, 5, 26), _dt(2026, 5, 29))
        assert result["drift"]["drifted"] == 1

    def test_null_severity_prose_fallback_drifted(self) -> None:
        """severity=None + non-empty variance → prose fallback, drifted."""
        ts = "2026-05-27T12:00:00+00:00"
        rec = _make_record(
            session_id="s1",
            variance="added extra stuff",
            severity=None,
            timestamp=ts,
        )
        result = aggregate_drift([rec], _dt(2026, 5, 26), _dt(2026, 5, 29))
        assert result["drift"]["drifted"] == 1

    def test_null_severity_prose_fallback_clean(self) -> None:
        """severity=None + 'no variance' → prose fallback, clean."""
        ts = "2026-05-27T12:00:00+00:00"
        rec = _make_record(
            session_id="s1",
            variance="no variance",
            severity=None,
            timestamp=ts,
        )
        result = aggregate_drift([rec], _dt(2026, 5, 26), _dt(2026, 5, 29))
        assert result["drift"]["drifted"] == 0
        assert result["drift"]["clean"] == 1

    def test_drift_rate_rounded_to_3_decimals(self) -> None:
        """drift_rate is rounded to exactly 3 decimal places."""
        from_dt = _dt(2026, 5, 26)
        to_dt = _dt(2026, 6, 2)
        # 1 drifted out of 3 = 0.333...
        records = []
        for i, (sev, ts_day) in enumerate([(1, "05-26"), (0, "05-27"), (0, "05-28")]):
            records.append(
                _make_record(
                    session_id=f"s{i}",
                    severity=sev,
                    timestamp=f"2026-{ts_day}T12:00:00+00:00",
                )
            )
        result = aggregate_drift(records, from_dt, to_dt)
        assert result["drift"]["drift_rate"] == round(1 / 3, 3)

    def test_severity_distribution_invariant(self) -> None:
        """sum(severity_distribution.values()) == total_records."""
        from_dt = _dt(2026, 5, 26)
        to_dt = _dt(2026, 6, 2)
        records = [
            _make_record(
                session_id="a",
                severity=0,
                timestamp="2026-05-27T00:00:00+00:00",
            ),
            _make_record(
                session_id="b",
                severity=1,
                timestamp="2026-05-28T00:00:00+00:00",
            ),
            _make_record(
                session_id="c",
                severity=2,
                timestamp="2026-05-29T00:00:00+00:00",
            ),
            _make_record(
                session_id="d",
                severity=None,
                timestamp="2026-05-30T00:00:00+00:00",
            ),
        ]
        result = aggregate_drift(records, from_dt, to_dt)
        dist_sum = sum(result["severity_distribution"].values())
        assert dist_sum == result["total_records"]

    def test_window_filtering_excludes_out_of_range(self) -> None:
        """Records outside [from, to) are excluded from totals."""
        # Record is from May 10, window is May 26–Jun 2
        rec_old = _make_record(
            session_id="old",
            severity=1,
            timestamp="2026-05-10T00:00:00+00:00",
        )
        rec_in = _make_record(
            session_id="in",
            severity=0,
            timestamp="2026-05-27T00:00:00+00:00",
        )
        result = aggregate_drift([rec_old, rec_in], _dt(2026, 5, 26), _dt(2026, 6, 2))
        assert result["total_records"] == 1

    def test_window_boundary_to_is_exclusive(self) -> None:
        """Record at exactly to_dt is excluded (half-open interval)."""
        ts_at_boundary = "2026-06-02T00:00:00+00:00"
        rec = _make_record(
            session_id="boundary",
            severity=1,
            timestamp=ts_at_boundary,
        )
        result = aggregate_drift([rec], _dt(2026, 5, 26), _dt(2026, 6, 2))
        assert result["total_records"] == 0

    def test_records_without_timestamp_counted(self) -> None:
        """Records using mtime fallback increment records_without_timestamp."""
        rec = _make_record(session_id="s1", severity=0, timestamp=None)
        # Provide a mtime in range: May 27
        mtime_in_range = datetime(2026, 5, 27, tzinfo=_UTC).timestamp()
        # We need to pass raw records — aggregate_drift uses file_mtime
        # from record metadata injected by load_variance_records.
        # Since we test aggregate_drift directly, we inject _mtime into rec.
        rec["_mtime"] = mtime_in_range
        result = aggregate_drift([rec], _dt(2026, 5, 26), _dt(2026, 6, 2))
        assert result["records_without_timestamp"] == 1

    def test_trend_includes_zero_record_days(self) -> None:
        """Days in window with no records still appear in trend."""
        ts = "2026-05-27T12:00:00+00:00"
        rec = _make_record(session_id="s1", severity=0, timestamp=ts)
        from_dt = _dt(2026, 5, 26)
        to_dt = _dt(2026, 5, 29)  # 3 days: 26, 27, 28
        result = aggregate_drift([rec], from_dt, to_dt)
        dates = [e["date"] for e in result["trend"]]
        assert "2026-05-26" in dates
        assert "2026-05-27" in dates
        assert "2026-05-28" in dates
        # May 26 should have zero records (record is May 27)
        day26 = next(e for e in result["trend"] if e["date"] == "2026-05-26")
        assert day26["total"] == 0

    def test_window_field_in_output(self) -> None:
        """Output contains window.from and window.to as ISO strings."""
        from_dt = _dt(2026, 5, 26)
        to_dt = _dt(2026, 6, 2)
        result = aggregate_drift([], from_dt, to_dt)
        assert "window" in result
        assert result["window"]["from"] == from_dt.isoformat()
        assert result["window"]["to"] == to_dt.isoformat()

    def test_skipped_records_initialises_to_zero(self) -> None:
        """aggregate_drift itself doesn't set skipped_records (loader does)."""
        result = aggregate_drift([], _dt(2026, 5, 26), _dt(2026, 6, 2))
        # aggregate_drift should include skipped_records = 0 in output shape
        assert "skipped_records" in result
        assert result["skipped_records"] == 0


# ---------------------------------------------------------------------------
# load_variance_records
# ---------------------------------------------------------------------------


class TestLoadVarianceRecords:
    """Tests for load_variance_records()."""

    def test_loads_valid_records(self, tmp_path: Path) -> None:
        """Valid JSON files in variance/ are loaded."""
        records = [
            _make_record(session_id="s1"),
            _make_record(session_id="s2"),
        ]
        _write_records(tmp_path, records)
        loaded = load_variance_records(tmp_path)
        assert len(loaded) == 2

    def test_skips_malformed_json(self, tmp_path: Path) -> None:
        """Malformed JSON is skipped silently."""
        var_dir = tmp_path / "variance"
        var_dir.mkdir()
        # Write one valid and one invalid file
        (var_dir / "good.json").write_text(
            json.dumps(_make_record(session_id="good")), encoding="utf-8"
        )
        (var_dir / "bad.json").write_text("{ not valid json }", encoding="utf-8")
        loaded = load_variance_records(tmp_path)
        assert len(loaded) == 1
        assert loaded[0]["session_id"] == "good"

    def test_skipped_count_in_result(self, tmp_path: Path) -> None:
        """skipped_records count is available via the loader metadata."""
        var_dir = tmp_path / "variance"
        var_dir.mkdir()
        (var_dir / "good.json").write_text(
            json.dumps(_make_record(session_id="good")), encoding="utf-8"
        )
        (var_dir / "bad.json").write_text("INVALID", encoding="utf-8")
        # load_variance_records returns enriched dicts;
        # test that exactly 1 record is returned (bad skipped)
        loaded = load_variance_records(tmp_path)
        assert len(loaded) == 1

    def test_missing_variance_dir_returns_empty(self, tmp_path: Path) -> None:
        """Missing variance/ dir returns empty list (not an error)."""
        loaded = load_variance_records(tmp_path)
        assert loaded == []

    def test_empty_variance_dir_returns_empty(self, tmp_path: Path) -> None:
        """Empty variance/ dir returns empty list."""
        (tmp_path / "variance").mkdir()
        loaded = load_variance_records(tmp_path)
        assert loaded == []

    def test_mtime_injected_into_records(self, tmp_path: Path) -> None:
        """Loaded records have _mtime injected for fallback use."""
        _write_records(tmp_path, [_make_record(session_id="s1")])
        loaded = load_variance_records(tmp_path)
        assert "_mtime" in loaded[0]
        assert isinstance(loaded[0]["_mtime"], float)


# ---------------------------------------------------------------------------
# render_text
# ---------------------------------------------------------------------------


class TestRenderText:
    """Tests for render_text()."""

    def _make_report(
        self,
        *,
        drifted: int = 2,
        total: int = 5,
        records_without_ts: int = 0,
    ) -> dict:
        """Build a minimal report dict for render_text."""
        rate = round(drifted / total, 3) if total else 0.0
        return {
            "window": {
                "from": "2026-05-26T00:00:00+00:00",
                "to": "2026-06-02T00:00:00+00:00",
            },
            "total_records": total,
            "skipped_records": 0,
            "records_without_timestamp": records_without_ts,
            "drift": {
                "drifted": drifted,
                "clean": total - drifted,
                "drift_rate": rate,
            },
            "severity_distribution": {
                "0": total - drifted,
                "1": drifted,
                "2": 0,
                "3": 0,
                "null": 0,
            },
            "trend": [
                {
                    "date": "2026-05-26",
                    "total": total,
                    "drifted": drifted,
                    "drift_rate": rate,
                }
            ],
        }

    def test_output_is_string(self) -> None:
        """render_text returns a string."""
        report = self._make_report()
        assert isinstance(render_text(report), str)

    def test_header_contains_dates(self) -> None:
        """Header line includes from/to dates."""
        report = self._make_report()
        text = render_text(report)
        assert "2026-05-26" in text
        assert "2026-06-02" in text

    def test_shows_drifted_fraction(self) -> None:
        """Output shows drifted count and total."""
        report = self._make_report(drifted=2, total=5)
        text = render_text(report)
        assert "2" in text
        assert "5" in text

    def test_no_timestamp_warning_when_zero(self) -> None:
        """No mtime warning when records_without_timestamp is 0."""
        report = self._make_report(records_without_ts=0)
        text = render_text(report)
        assert "mtime" not in text
        assert "temporal" not in text

    def test_timestamp_warning_when_nonzero(self) -> None:
        """Warning line appears when records_without_timestamp > 0."""
        report = self._make_report(records_without_ts=3)
        text = render_text(report)
        assert "mtime" in text

    def test_trend_section_present(self) -> None:
        """Trend section header is present."""
        report = self._make_report()
        text = render_text(report)
        assert "Trend" in text or "trend" in text

    def test_ascii_only_no_unicode_bars(self) -> None:
        """Output contains only ASCII (no Unicode sparklines)."""
        report = self._make_report()
        text = render_text(report)
        assert text.isascii()

    def test_no_color_codes(self) -> None:
        """No ANSI escape sequences in output."""
        report = self._make_report()
        text = render_text(report)
        assert "\x1b[" not in text


# ---------------------------------------------------------------------------
# End-to-end via subprocess run()
# ---------------------------------------------------------------------------


class TestRunCLI:
    """End-to-end tests exercising run() through the CLI entry point."""

    def test_default_7d_window_json_output(self, tmp_path: Path) -> None:
        """--window 7d (default) produces correct window.from/to in JSON."""
        ts_now = datetime.now(_UTC)
        ts_in_window = (ts_now - timedelta(days=3)).isoformat()
        rec = _make_record(session_id="recent", severity=0, timestamp=ts_in_window)
        _write_records(tmp_path, [rec])

        result = _run_cli("--base-dir", str(tmp_path), "--format", "json")
        assert result.returncode == EXIT_OK
        data = json.loads(result.stdout)
        assert "window" in data
        # from should be approximately 7 days ago
        from_dt = datetime.fromisoformat(data["window"]["from"])
        diff_hours = (ts_now - from_dt).total_seconds() / 3600
        # Allow ±5 minutes tolerance
        assert 167.9 <= diff_hours <= 168.1

    def test_json_output_shape(self, tmp_path: Path) -> None:
        """JSON output matches the §4.1 required top-level fields."""
        _write_records(tmp_path, [])
        result = _run_cli(
            "--base-dir",
            str(tmp_path),
            "--window",
            "7d",
            "--format",
            "json",
        )
        assert result.returncode == EXIT_OK
        data = json.loads(result.stdout)
        for key in (
            "window",
            "total_records",
            "skipped_records",
            "records_without_timestamp",
            "drift",
            "severity_distribution",
            "trend",
        ):
            assert key in data, f"Missing key: {key}"

    def test_format_text_runs_without_crashing(self, tmp_path: Path) -> None:
        """--format text produces output and exits 0."""
        ts = (datetime.now(_UTC) - timedelta(days=1)).isoformat()
        _write_records(
            tmp_path,
            [_make_record(session_id="s1", severity=1, timestamp=ts)],
        )
        result = _run_cli("--base-dir", str(tmp_path), "--format", "text")
        assert result.returncode == EXIT_OK
        assert len(result.stdout) > 0

    def test_format_text_spot_check_line(self, tmp_path: Path) -> None:
        """--format text output contains 'Drift report'."""
        result = _run_cli("--base-dir", str(tmp_path), "--format", "text")
        assert result.returncode == EXIT_OK
        assert "Drift report" in result.stdout

    def test_window_and_from_are_mutually_exclusive(self, tmp_path: Path) -> None:
        """--window and --from together produce an error exit."""
        result = _run_cli(
            "--base-dir",
            str(tmp_path),
            "--window",
            "7d",
            "--from",
            "2026-05-01",
        )
        assert result.returncode != EXIT_OK

    def test_bad_window_format_exits_nonzero(self, tmp_path: Path) -> None:
        """Invalid --window value exits non-zero."""
        result = _run_cli("--base-dir", str(tmp_path), "--window", "badval")
        assert result.returncode != EXIT_OK

    def test_bad_from_format_exits_nonzero(self, tmp_path: Path) -> None:
        """Invalid --from date exits non-zero."""
        result = _run_cli(
            "--base-dir",
            str(tmp_path),
            "--from",
            "not-a-date",
        )
        assert result.returncode != EXIT_OK

    def test_inverted_range_exits_nonzero(self, tmp_path: Path) -> None:
        """--from after --to exits non-zero."""
        result = _run_cli(
            "--base-dir",
            str(tmp_path),
            "--from",
            "2026-06-01",
            "--to",
            "2026-05-01",
        )
        assert result.returncode != EXIT_OK

    def test_window_exceeding_366_days_exits_nonzero(self, tmp_path: Path) -> None:
        """Window > 366 days exits non-zero."""
        result = _run_cli(
            "--base-dir",
            str(tmp_path),
            "--from",
            "2024-01-01",
            "--to",
            "2026-01-01",
        )
        assert result.returncode != EXIT_OK

    def test_empty_variance_dir_exits_ok(self, tmp_path: Path) -> None:
        """Empty variance/ dir produces zero report and exits 0."""
        (tmp_path / "variance").mkdir()
        result = _run_cli("--base-dir", str(tmp_path), "--format", "json")
        assert result.returncode == EXIT_OK
        data = json.loads(result.stdout)
        assert data["total_records"] == 0

    def test_missing_variance_dir_exits_ok(self, tmp_path: Path) -> None:
        """Missing variance/ dir (no dir at all) exits 0 with empty report."""
        result = _run_cli("--base-dir", str(tmp_path), "--format", "json")
        assert result.returncode == EXIT_OK
        data = json.loads(result.stdout)
        assert data["total_records"] == 0

    def test_malformed_json_record_skipped_and_counted(self, tmp_path: Path) -> None:
        """One malformed + one valid → total=1, skipped=1, exit 0."""
        var_dir = tmp_path / "variance"
        var_dir.mkdir()
        ts = (datetime.now(_UTC) - timedelta(days=1)).isoformat()
        good = _make_record(session_id="good", severity=0, timestamp=ts)
        (var_dir / "good.json").write_text(json.dumps(good), encoding="utf-8")
        (var_dir / "bad.json").write_text("NOT JSON", encoding="utf-8")

        result = _run_cli(
            "--base-dir",
            str(tmp_path),
            "--window",
            "7d",
            "--format",
            "json",
        )
        assert result.returncode == EXIT_OK
        data = json.loads(result.stdout)
        assert data["total_records"] == 1
        assert data["skipped_records"] == 1

    def test_from_without_to_defaults_to_now(self, tmp_path: Path) -> None:
        """--from without --to uses current time as to_dt."""
        result = _run_cli(
            "--base-dir",
            str(tmp_path),
            "--from",
            "2026-05-01",
            "--format",
            "json",
        )
        assert result.returncode == EXIT_OK
        data = json.loads(result.stdout)
        # to should be approximately now (within a minute)
        to_dt = datetime.fromisoformat(data["window"]["to"])
        now = datetime.now(_UTC)
        diff_secs = abs((now - to_dt).total_seconds())
        assert diff_secs < 60

    def test_severity_distribution_all_five_keys(self, tmp_path: Path) -> None:
        """severity_distribution always has keys 0, 1, 2, 3, null."""
        result = _run_cli("--base-dir", str(tmp_path), "--format", "json")
        data = json.loads(result.stdout)
        assert set(data["severity_distribution"].keys()) == {
            "0",
            "1",
            "2",
            "3",
            "null",
        }
