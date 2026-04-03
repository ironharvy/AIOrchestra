"""Tests for the --watch loop."""

import signal

from aiorchestra.cli import _watch_loop, build_parser


def test_watch_loop_calls_fn_and_stops_on_shutdown():
    """The loop calls fn, then exits when the shutdown flag is set."""
    call_count = 0

    def fake_dispatch():
        nonlocal call_count
        call_count += 1
        # Simulate SIGTERM arriving after first cycle
        signal.raise_signal(signal.SIGTERM)
        return 0

    result = _watch_loop(fake_dispatch, poll_interval=1)

    assert result == 0
    assert call_count == 1


def test_watch_loop_runs_multiple_cycles(monkeypatch):
    """The loop runs fn repeatedly until shutdown."""
    call_count = 0

    def fake_dispatch():
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            signal.raise_signal(signal.SIGINT)
        return 0

    # Patch time.sleep to avoid real delays
    monkeypatch.setattr("time.sleep", lambda _: None)

    result = _watch_loop(fake_dispatch, poll_interval=1)

    assert result == 0
    assert call_count == 3


def test_watch_loop_tolerates_fn_failure(monkeypatch):
    """Non-zero return from fn doesn't stop the loop — only signals do."""
    call_count = 0

    def failing_dispatch():
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            signal.raise_signal(signal.SIGTERM)
        return 1

    monkeypatch.setattr("time.sleep", lambda _: None)

    result = _watch_loop(failing_dispatch, poll_interval=1)

    assert result == 0
    assert call_count == 2


def test_cli_parser_watch_flags_dispatch():
    parser = build_parser()
    args = parser.parse_args(["dispatch", "--watch", "--poll-interval", "60"])

    assert args.watch is True
    assert args.poll_interval == 60


def test_cli_parser_watch_flags_run():
    parser = build_parser()
    args = parser.parse_args(["run", "--repo", "o/r", "--watch", "--poll-interval", "120"])

    assert args.watch is True
    assert args.poll_interval == 120


def test_cli_parser_watch_defaults():
    parser = build_parser()
    args = parser.parse_args(["dispatch"])

    assert args.watch is False
    assert args.poll_interval is None
