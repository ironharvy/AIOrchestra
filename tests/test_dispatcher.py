"""Tests for the multi-repo dispatcher and agent resolution."""

from aiorchestra.ai import normalize_agent_family, resolve_agent
from aiorchestra.cli import build_parser
from aiorchestra.dispatcher import Dispatcher


# ---------------------------------------------------------------------------
# resolve_agent
# ---------------------------------------------------------------------------


def test_resolve_agent_explicit_claude():
    assert resolve_agent(["aiorchestra", "claude"]) == "claude"


def test_resolve_agent_explicit_codex():
    assert resolve_agent(["aiorchestra", "codex"]) == "codex"


def test_resolve_agent_explicit_jules():
    assert resolve_agent(["aiorchestra", "jules"]) == "jules"


def test_resolve_agent_defaults_when_no_agent_label():
    assert resolve_agent(["aiorchestra", "bug"]) == "claude"


def test_resolve_agent_custom_default():
    assert resolve_agent(["aiorchestra"], default="codex") == "codex"


def test_resolve_agent_first_match_wins():
    assert resolve_agent(["codex", "jules"]) == "codex"


def test_resolve_agent_case_insensitive():
    assert resolve_agent(["CLAUDE"]) == "claude"


def test_resolve_agent_substring_match():
    assert resolve_agent(["claude-code"]) == "claude"


def test_resolve_agent_empty_labels():
    assert resolve_agent([]) == "claude"


# ---------------------------------------------------------------------------
# normalize_agent_family
# ---------------------------------------------------------------------------


def test_normalize_agent_family_jules():
    assert normalize_agent_family("jules") == "jules"


def test_normalize_agent_family_gemini():
    assert normalize_agent_family("gemini") == "gemini"


def test_normalize_agent_family_codex():
    assert normalize_agent_family("codex") == "codex"


def test_normalize_agent_family_codex_v2():
    assert normalize_agent_family("codex-v2") == "codex"


def test_normalize_agent_family_claude_code():
    assert normalize_agent_family("claude-code") == "claude"


def test_normalize_agent_family_none():
    assert normalize_agent_family(None) == "claude"


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def test_dispatcher_no_issues_returns_zero(monkeypatch):
    monkeypatch.setattr(
        "aiorchestra.dispatcher.discover_all_issues",
        lambda owner: {},
    )

    dispatcher = Dispatcher(config={}, owner="@me")
    assert dispatcher.run() == 0


def test_dispatcher_fans_out_to_pipelines(monkeypatch):
    pipeline_calls = []

    monkeypatch.setattr(
        "aiorchestra.dispatcher.discover_all_issues",
        lambda owner: {
            "owner/repo-a": [
                {"number": 1, "title": "A", "labels": ["aiorchestra", "claude"]},
            ],
            "owner/repo-b": [
                {"number": 5, "title": "B", "labels": ["aiorchestra"]},
            ],
        },
    )

    class FakePipeline:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def run(self, issues=None):
            pipeline_calls.append((self.kwargs["repo"], self.kwargs["label"], issues))
            return 0

    monkeypatch.setattr("aiorchestra.dispatcher.Pipeline", FakePipeline)

    dispatcher = Dispatcher(config={"ai": {"provider": "claude-code"}}, owner="@me")
    assert dispatcher.run() == 0

    assert len(pipeline_calls) == 2
    assert pipeline_calls[0][0] == "owner/repo-a"
    assert pipeline_calls[0][1] == "claude"
    assert pipeline_calls[1][0] == "owner/repo-b"
    assert pipeline_calls[1][1] == "claude"


def test_dispatcher_stops_on_pipeline_failure(monkeypatch):
    monkeypatch.setattr(
        "aiorchestra.dispatcher.discover_all_issues",
        lambda owner: {
            "owner/repo-a": [
                {"number": 1, "title": "A", "labels": ["aiorchestra"]},
            ],
            "owner/repo-b": [
                {"number": 2, "title": "B", "labels": ["aiorchestra"]},
            ],
        },
    )

    class FailingPipeline:
        def __init__(self, **kwargs):
            pass

        def run(self, issues=None):
            return 1

    monkeypatch.setattr("aiorchestra.dispatcher.Pipeline", FailingPipeline)

    dispatcher = Dispatcher(config={}, owner="@me")
    assert dispatcher.run() == 1


def test_dispatcher_passes_config_and_flags(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "aiorchestra.dispatcher.discover_all_issues",
        lambda owner: {
            "owner/repo": [
                {"number": 1, "title": "X", "labels": ["aiorchestra"]},
            ],
        },
    )

    class CapturePipeline:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self, issues=None):
            return 0

    monkeypatch.setattr("aiorchestra.dispatcher.Pipeline", CapturePipeline)

    dispatcher = Dispatcher(
        config={"ai": {"provider": "claude-code"}},
        owner="myorg",
        config_path="custom.yaml",
        dry_run=True,
        workspace="/tmp/ws",
    )
    dispatcher.run()

    assert captured["repo"] == "owner/repo"
    assert captured["config_path"] == "custom.yaml"
    assert captured["dry_run"] is True
    assert captured["workspace"] == "/tmp/ws"


# ---------------------------------------------------------------------------
# CLI dispatch subcommand
# ---------------------------------------------------------------------------


def test_cli_dispatch_defaults():
    parser = build_parser()
    args = parser.parse_args(["dispatch"])

    assert args.command == "dispatch"
    assert args.owner == "@me"
    assert args.config is None
    assert args.workspace is None
    assert args.dry_run is False
    assert args.verbose is False


def test_cli_dispatch_with_flags():
    parser = build_parser()
    args = parser.parse_args(
        [
            "dispatch",
            "--owner",
            "myorg",
            "--config",
            "custom.yaml",
            "--workspace",
            "/tmp/ws",
            "--dry-run",
            "-v",
        ]
    )

    assert args.owner == "myorg"
    assert args.config == "custom.yaml"
    assert args.workspace == "/tmp/ws"
    assert args.dry_run is True
    assert args.verbose is True


# ---------------------------------------------------------------------------
# Pipeline.run(issues=...) — pre-supplied issues
# ---------------------------------------------------------------------------


def test_pipeline_run_with_presupplied_issues(monkeypatch, tmp_path):
    """Pipeline.run(issues=...) skips discovery and processes the given issues."""
    from aiorchestra.pipeline import Pipeline

    calls = []

    monkeypatch.setattr(
        "aiorchestra.pipeline.prepare_environment",
        lambda repo, branch, workspace: str(tmp_path),
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.load_config",
        lambda path, repo_root=None: {
            "ai": {"max_retries": 1},
            "ci": {"enabled": False},
            "review": {"enabled": False},
        },
    )
    monkeypatch.setattr("aiorchestra.pipeline._has_changes", lambda repo_root: True)
    monkeypatch.setattr("aiorchestra.pipeline.enrich_issue", lambda issue, config: "")

    def fake_implement(
        issue,
        config,
        prompt_name="implement",
        error_text=None,
        repo_root=None,
        osint_context="",
        repo=None,
    ):
        from aiorchestra.ai import InvokeResult

        calls.append(("implement", issue["number"]))
        return InvokeResult(success=True)

    def fake_validate(config, repo_root=None):
        return True, None

    def fake_publish(repo, branch, issue, repo_root, pr_url=None):
        calls.append(("publish", issue["number"]))
        return "https://example.test/pr/1"

    monkeypatch.setattr("aiorchestra.pipeline.implement", fake_implement)
    monkeypatch.setattr("aiorchestra.pipeline.validate", fake_validate)
    monkeypatch.setattr("aiorchestra.pipeline.publish", fake_publish)

    monkeypatch.setattr("aiorchestra.pipeline.add_label", lambda repo, number, label: True)
    monkeypatch.setattr("aiorchestra.pipeline.remove_label", lambda repo, number, label: True)

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
        parallel=False,
    )

    pre_issues = [
        {"number": 10, "title": "Pre-supplied A"},
        {"number": 20, "title": "Pre-supplied B"},
    ]

    assert pipeline.run(issues=pre_issues) == 0
    assert ("implement", 10) in calls
    assert ("implement", 20) in calls
    assert ("publish", 10) in calls
    assert ("publish", 20) in calls
