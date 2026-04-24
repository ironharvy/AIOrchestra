"""Tests for aiorchestra.stages.ci — CI polling logic."""

import json
import types

from aiorchestra.stages import ci as ci_mod
from aiorchestra.stages.ci import _is_no_checks_error, wait_for_ci


def _make_result(returncode=0, stdout="", stderr=""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class TestIsNoChecksError:
    def test_matches_gh_cli_message(self):
        assert _is_no_checks_error("no checks reported on the 'main' branch")

    def test_case_insensitive(self):
        assert _is_no_checks_error("No Checks Reported on the 'main' branch")

    def test_no_match(self):
        assert not _is_no_checks_error("HTTP 502: server error")


class TestWaitForCiNoChecksGrace:
    """When a repo has no CI checks, wait_for_ci should pass after the grace period."""

    def test_no_checks_stderr_passes_after_grace(self, monkeypatch):
        """gh pr checks returns non-zero with 'no checks reported' — should pass."""
        clock = [0.0]

        def fake_monotonic():
            return clock[0]

        def fake_sleep(seconds):
            clock[0] += seconds

        def fake_run(cmd, logger=None):
            return _make_result(
                returncode=1,
                stderr="no checks reported on the 'codex/1' branch",
            )

        monkeypatch.setattr(ci_mod, "run_command", fake_run)
        monkeypatch.setattr(ci_mod.time, "monotonic", fake_monotonic)
        monkeypatch.setattr(ci_mod.time, "sleep", fake_sleep)

        ok, output = wait_for_ci(
            "https://pr/1",
            {"ci": {"timeout": 600, "poll_interval": 10, "no_checks_grace": 30}},
        )
        assert ok is True
        assert output is None

    def test_no_checks_empty_json_passes_after_grace(self, monkeypatch):
        """gh pr checks returns 0 with empty array — should pass."""
        clock = [0.0]

        def fake_monotonic():
            return clock[0]

        def fake_sleep(seconds):
            clock[0] += seconds

        def fake_run(cmd, logger=None):
            return _make_result(returncode=0, stdout="[]")

        monkeypatch.setattr(ci_mod, "run_command", fake_run)
        monkeypatch.setattr(ci_mod.time, "monotonic", fake_monotonic)
        monkeypatch.setattr(ci_mod.time, "sleep", fake_sleep)

        ok, output = wait_for_ci(
            "https://pr/1",
            {"ci": {"timeout": 600, "poll_interval": 10, "no_checks_grace": 25}},
        )
        assert ok is True
        assert output is None

    def test_no_checks_grace_resets_when_real_error(self, monkeypatch):
        """A non-'no checks' error should reset the grace timer."""
        clock = [0.0]
        call_count = [0]

        def fake_monotonic():
            return clock[0]

        def fake_sleep(seconds):
            clock[0] += seconds

        def fake_run(cmd, logger=None):
            call_count[0] += 1
            if call_count[0] <= 2:
                return _make_result(
                    returncode=1,
                    stderr="no checks reported on the 'main' branch",
                )
            if call_count[0] == 3:
                return _make_result(returncode=1, stderr="HTTP 502: server error")
            return _make_result(
                returncode=1,
                stderr="no checks reported on the 'main' branch",
            )

        monkeypatch.setattr(ci_mod, "run_command", fake_run)
        monkeypatch.setattr(ci_mod.time, "monotonic", fake_monotonic)
        monkeypatch.setattr(ci_mod.time, "sleep", fake_sleep)

        ok, output = wait_for_ci(
            "https://pr/1",
            {"ci": {"timeout": 600, "poll_interval": 10, "no_checks_grace": 25}},
        )
        assert ok is True
        assert output is None
        # Should take longer because the HTTP error resets the grace timer
        assert call_count[0] > 3

    def test_checks_appear_after_grace_wait(self, monkeypatch):
        """If checks appear during the grace period, normal logic takes over."""
        clock = [0.0]
        call_count = [0]

        def fake_monotonic():
            return clock[0]

        def fake_sleep(seconds):
            clock[0] += seconds

        def fake_run(cmd, logger=None):
            call_count[0] += 1
            if call_count[0] <= 2:
                return _make_result(
                    returncode=1,
                    stderr="no checks reported on the 'main' branch",
                )
            checks = [{"name": "test", "bucket": "pass", "state": "SUCCESS"}]
            return _make_result(returncode=0, stdout=json.dumps(checks))

        monkeypatch.setattr(ci_mod, "run_command", fake_run)
        monkeypatch.setattr(ci_mod.time, "monotonic", fake_monotonic)
        monkeypatch.setattr(ci_mod.time, "sleep", fake_sleep)

        ok, output = wait_for_ci(
            "https://pr/1",
            {"ci": {"timeout": 600, "poll_interval": 10, "no_checks_grace": 120}},
        )
        assert ok is True
        assert output is None

    def test_default_grace_period_is_120(self, monkeypatch):
        """Without explicit config, grace period defaults to 120s."""
        clock = [0.0]

        def fake_monotonic():
            return clock[0]

        def fake_sleep(seconds):
            clock[0] += seconds

        def fake_run(cmd, logger=None):
            return _make_result(returncode=0, stdout="[]")

        monkeypatch.setattr(ci_mod, "run_command", fake_run)
        monkeypatch.setattr(ci_mod.time, "monotonic", fake_monotonic)
        monkeypatch.setattr(ci_mod.time, "sleep", fake_sleep)

        ok, _ = wait_for_ci("https://pr/1", {"ci": {"timeout": 600, "poll_interval": 30}})
        assert ok is True
        # With 30s poll interval and 120s grace, should take ~4 polls (120/30)
        assert clock[0] >= 120
        assert clock[0] < 180
