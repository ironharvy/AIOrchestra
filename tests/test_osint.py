"""Tests for the OSINT enrichment stage."""

import types

from aiorchestra.stages.osint import (
    CollectorResult,
    OsintReport,
    extract_targets,
    enrich_issue,
    gather,
    _pick_collectors,
)


# ------------------------------------------------------------------
# Target extraction
# ------------------------------------------------------------------

class TestExtractTargets:
    def test_extracts_domains(self):
        text = "Please scan example-target.org and check api.example-target.org"
        targets = extract_targets(text)
        assert "example-target.org" in targets
        assert "api.example-target.org" in targets

    def test_extracts_ipv4(self):
        text = "The server at 192.168.1.100 is unreachable"
        targets = extract_targets(text)
        assert "192.168.1.100" in targets

    def test_ignores_common_domains(self):
        text = "See https://github.com/owner/repo for details about target.io"
        targets = extract_targets(text)
        assert "github.com" not in targets
        assert "target.io" in targets

    def test_deduplicates(self):
        text = "Check target.io and also target.io again"
        targets = extract_targets(text)
        assert targets.count("target.io") == 1

    def test_empty_text(self):
        assert extract_targets("") == []

    def test_no_targets(self):
        assert extract_targets("Just a regular issue about refactoring") == []


# ------------------------------------------------------------------
# OsintReport
# ------------------------------------------------------------------

class TestOsintReport:
    def test_has_data_with_results(self):
        report = OsintReport(results=[
            CollectorResult(name="whois", target="t.io", raw="data", success=True),
        ])
        assert report.has_data is True

    def test_has_data_empty(self):
        report = OsintReport()
        assert report.has_data is False

    def test_has_data_all_failed(self):
        report = OsintReport(results=[
            CollectorResult(name="whois", target="t.io", raw="", success=False),
        ])
        assert report.has_data is False

    def test_raw_text(self):
        report = OsintReport(results=[
            CollectorResult(name="whois", target="t.io", raw="registrar: X", success=True),
            CollectorResult(name="dig", target="t.io", raw="1.2.3.4", success=True),
            CollectorResult(name="nmap", target="t.io", raw="", success=False),
        ])
        raw = report.raw_text()
        assert "whois" in raw
        assert "registrar: X" in raw
        assert "1.2.3.4" in raw
        assert "nmap" not in raw  # failed collector excluded

    def test_context_prefers_summary(self):
        report = OsintReport(
            results=[CollectorResult(name="whois", target="t", raw="raw", success=True)],
            summary="structured summary",
        )
        assert report.context_for_prompt() == "structured summary"

    def test_context_falls_back_to_raw(self):
        report = OsintReport(
            results=[CollectorResult(name="whois", target="t", raw="raw data", success=True)],
        )
        assert "raw data" in report.context_for_prompt()


# ------------------------------------------------------------------
# Collector picking
# ------------------------------------------------------------------

class TestPickCollectors:
    def test_defaults(self):
        result = _pick_collectors({})
        assert "whois" in result
        assert "dig" in result

    def test_custom_list(self):
        result = _pick_collectors({"collectors": ["dig", "host"]})
        assert result == ["dig", "host"]

    def test_csv_string(self):
        result = _pick_collectors({"collectors": "dig, host"})
        assert result == ["dig", "host"]

    def test_invalid_collector_filtered(self):
        result = _pick_collectors({"collectors": ["dig", "nonexistent"]})
        assert result == ["dig"]


# ------------------------------------------------------------------
# Gather (integration with mocked shell)
# ------------------------------------------------------------------

def test_gather_no_targets():
    report = gather([], {})
    assert not report.has_data


def test_gather_skips_missing_tools(monkeypatch):
    """Collectors whose binaries aren't on PATH are skipped gracefully."""
    monkeypatch.setattr("aiorchestra.stages.osint.shutil.which", lambda _: None)

    report = gather(["target.io"], {"collectors": ["whois", "dig"]})
    assert not report.has_data
    assert len(report.results) == 2
    assert all(not r.success for r in report.results)


def test_gather_with_working_collectors(monkeypatch):
    """Collectors that succeed contribute to the report."""
    monkeypatch.setattr("aiorchestra.stages.osint.shutil.which", lambda _: "/usr/bin/fake")

    def fake_run(cmd, *, cwd=None, check=False, shell=None, logger=None):
        return types.SimpleNamespace(returncode=0, stdout="result data", stderr="")

    monkeypatch.setattr("aiorchestra.stages.osint.run_command", fake_run)

    # Disable Ollama to test raw path
    monkeypatch.setattr("aiorchestra.stages.osint.ollama_available", lambda _: False)

    report = gather(["target.io"], {"collectors": ["dig"]})
    assert report.has_data
    assert report.results[0].success
    assert "result data" in report.raw_text()


def test_gather_with_ollama_summary(monkeypatch):
    """When Ollama is available, raw output gets summarised."""
    monkeypatch.setattr("aiorchestra.stages.osint.shutil.which", lambda _: "/usr/bin/fake")

    def fake_run(cmd, *, cwd=None, check=False, shell=None, logger=None):
        return types.SimpleNamespace(returncode=0, stdout="raw whois", stderr="")

    monkeypatch.setattr("aiorchestra.stages.osint.run_command", fake_run)
    monkeypatch.setattr("aiorchestra.stages.osint.ollama_available", lambda _: True)
    monkeypatch.setattr(
        "aiorchestra.stages.osint.invoke_ollama",
        lambda prompt, config: "## Summary\nKey findings here",
    )

    report = gather(
        ["target.io"],
        {"collectors": ["whois"], "ollama": {"enabled": True}},
    )
    assert report.summary == "## Summary\nKey findings here"
    assert report.context_for_prompt() == "## Summary\nKey findings here"


# ------------------------------------------------------------------
# enrich_issue (stage entry point)
# ------------------------------------------------------------------

def test_enrich_issue_disabled():
    """Returns empty string when OSINT is disabled."""
    result = enrich_issue(
        {"number": 1, "title": "Test"},
        {"enabled": False},
    )
    assert result == ""


def test_enrich_issue_no_targets():
    """Returns empty string when no targets found in issue."""
    result = enrich_issue(
        {"number": 1, "title": "Refactor the config loader"},
        {"enabled": True},
    )
    assert result == ""


def test_enrich_issue_with_explicit_targets(monkeypatch):
    """Explicit targets in config bypass auto-extraction."""
    monkeypatch.setattr("aiorchestra.stages.osint.shutil.which", lambda _: "/usr/bin/fake")

    def fake_run(cmd, *, cwd=None, check=False, shell=None, logger=None):
        return types.SimpleNamespace(returncode=0, stdout="data", stderr="")

    monkeypatch.setattr("aiorchestra.stages.osint.run_command", fake_run)
    monkeypatch.setattr("aiorchestra.stages.osint.ollama_available", lambda _: False)

    result = enrich_issue(
        {"number": 1, "title": "No domains here"},
        {"enabled": True, "targets": ["explicit.io"], "collectors": ["dig"]},
    )
    assert result  # non-empty since we gave an explicit target


def test_enrich_issue_auto_extracts_targets(monkeypatch):
    """Targets are auto-extracted from issue body when not explicit."""
    monkeypatch.setattr("aiorchestra.stages.osint.shutil.which", lambda _: "/usr/bin/fake")

    def fake_run(cmd, *, cwd=None, check=False, shell=None, logger=None):
        return types.SimpleNamespace(returncode=0, stdout="dns-data", stderr="")

    monkeypatch.setattr("aiorchestra.stages.osint.run_command", fake_run)
    monkeypatch.setattr("aiorchestra.stages.osint.ollama_available", lambda _: False)

    result = enrich_issue(
        {"number": 5, "title": "Audit target.io", "body": "Check target.io infrastructure"},
        {"enabled": True, "collectors": ["dig"]},
    )
    assert "dns-data" in result
