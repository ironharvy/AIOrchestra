"""Tests for pipeline orchestration."""

import logging
import os
import types

from aiorchestra.ai import InvokeResult
from aiorchestra.pipeline import Pipeline


def test_issue_comments_passed_to_implement_prompt(monkeypatch, tmp_path):
    """Comments from issue discovery should appear in the implementation prompt."""
    captured_prompts = []

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

    def spy_implement(
        issue,
        config,
        prompt_name="implement",
        error_text=None,
        repo_root=None,
        osint_context="",
        repo=None,
    ):
        from aiorchestra.stages.implement import _build_prompt

        prompt = _build_prompt(issue, prompt_name, repo_root, error_text, osint_context)
        captured_prompts.append(prompt)
        return InvokeResult(success=True)

    monkeypatch.setattr("aiorchestra.pipeline.implement", spy_implement)
    monkeypatch.setattr(
        "aiorchestra.pipeline.validate", lambda config, repo_root=None: (True, None)
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.publish",
        lambda repo, branch, issue, repo_root, pr_url=None: "https://example.test/pr/1",
    )

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
    )

    issue = {
        "number": 5,
        "title": "Fix it",
        "body": "Details",
        "comments": [
            {"author": "alice", "body": "Try approach X instead"},
        ],
    }
    assert pipeline._process_issue(issue) is True
    assert len(captured_prompts) == 1
    assert "## Discussion" in captured_prompts[0]
    assert "@alice" in captured_prompts[0]
    assert "Try approach X instead" in captured_prompts[0]


def test_prepare_issue_reloads_repo_config(monkeypatch, tmp_path):
    calls: dict[str, str | None] = {}

    monkeypatch.setattr(
        "aiorchestra.pipeline.prepare_environment",
        lambda repo, branch, workspace: str(tmp_path),
    )

    def fake_load_config(path, repo_root=None):
        calls["path"] = path
        calls["repo_root"] = repo_root
        return {
            "ai": {"max_retries": 1},
            "ci": {"enabled": False},
            "review": {"enabled": False},
        }

    monkeypatch.setattr("aiorchestra.pipeline.load_config", fake_load_config)
    monkeypatch.setattr("aiorchestra.pipeline.enrich_issue", lambda issue, config: "")

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
        config_path="custom.yaml",
    )

    ctx = pipeline._prepare_issue({"number": 42, "title": "Refactor me"})

    assert ctx is not None
    assert ctx.branch == "claude/42"
    assert calls == {"path": "custom.yaml", "repo_root": str(tmp_path)}


def test_validation_retry_uses_fix_validation_prompt(monkeypatch, tmp_path):
    calls: list[tuple] = []
    cwd_before = os.getcwd()
    validate_results = iter([(False, "lint broke"), (True, None)])

    monkeypatch.setattr(
        "aiorchestra.pipeline.prepare_environment",
        lambda repo, branch, workspace: str(tmp_path),
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.load_config",
        lambda path, repo_root=None: {
            "ai": {"max_retries": 2},
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
        calls.append(("implement", prompt_name, error_text, repo_root))
        return InvokeResult(success=True)

    def fake_validate(config, repo_root=None):
        calls.append(("validate", repo_root))
        return next(validate_results)

    def fake_publish(repo, branch, issue, repo_root, pr_url=None):
        calls.append(("publish", pr_url, repo_root))
        return pr_url or "https://example.test/pr/1"

    monkeypatch.setattr("aiorchestra.pipeline.implement", fake_implement)
    monkeypatch.setattr("aiorchestra.pipeline.validate", fake_validate)
    monkeypatch.setattr("aiorchestra.pipeline.publish", fake_publish)

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
    )

    assert pipeline._process_issue({"number": 7, "title": "Fix validation loop"})
    assert os.getcwd() == cwd_before
    assert calls == [
        ("implement", "implement", None, str(tmp_path)),
        ("validate", str(tmp_path)),
        ("implement", "fix_validation", "lint broke", str(tmp_path)),
        ("validate", str(tmp_path)),
        ("publish", None, str(tmp_path)),
    ]


def test_ci_fix_revalidates_and_republishes(monkeypatch, tmp_path):
    calls: list[tuple] = []
    validate_results = iter([(True, None), (True, None)])
    ci_results = iter([(False, "ci broke"), (True, None)])

    monkeypatch.setattr(
        "aiorchestra.pipeline.prepare_environment",
        lambda repo, branch, workspace: str(tmp_path),
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.load_config",
        lambda path, repo_root=None: {
            "ai": {"max_retries": 2},
            "ci": {"enabled": True},
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
        calls.append(("implement", prompt_name, error_text, repo_root))
        return InvokeResult(success=True)

    def fake_validate(config, repo_root=None):
        calls.append(("validate", repo_root))
        return next(validate_results)

    def fake_publish(repo, branch, issue, repo_root, pr_url=None):
        calls.append(("publish", pr_url, repo_root))
        return pr_url or "https://example.test/pr/1"

    def fake_wait_for_ci(pr_url, config):
        calls.append(("wait_for_ci", pr_url))
        return next(ci_results)

    monkeypatch.setattr("aiorchestra.pipeline.implement", fake_implement)
    monkeypatch.setattr("aiorchestra.pipeline.validate", fake_validate)
    monkeypatch.setattr("aiorchestra.pipeline.publish", fake_publish)
    monkeypatch.setattr("aiorchestra.pipeline.wait_for_ci", fake_wait_for_ci)

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
    )

    assert pipeline._process_issue({"number": 9, "title": "Fix CI loop"})
    assert calls == [
        ("implement", "implement", None, str(tmp_path)),
        ("validate", str(tmp_path)),
        ("publish", None, str(tmp_path)),
        ("wait_for_ci", "https://example.test/pr/1"),
        ("implement", "fix_ci", "ci broke", str(tmp_path)),
        ("validate", str(tmp_path)),
        ("publish", "https://example.test/pr/1", str(tmp_path)),
        ("wait_for_ci", "https://example.test/pr/1"),
    ]


# ---------------------------------------------------------------------------
# Invariant tests
# ---------------------------------------------------------------------------


def test_no_changes_after_implement_aborts_immediately(monkeypatch, tmp_path):
    """Invariant 2: never proceed past implementation with zero file changes.

    If implement() returns True but the worktree is clean, the pipeline must
    NOT run validation, NOT retry — it must abort on the spot.
    """
    calls: list[tuple] = []

    monkeypatch.setattr(
        "aiorchestra.pipeline.prepare_environment",
        lambda repo, branch, workspace: str(tmp_path),
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.load_config",
        lambda path, repo_root=None: {
            "ai": {"max_retries": 3},
            "ci": {"enabled": False},
            "review": {"enabled": False},
        },
    )
    monkeypatch.setattr("aiorchestra.pipeline._has_changes", lambda repo_root: False)
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
        calls.append(("implement", prompt_name, error_text, repo_root))
        return InvokeResult(success=True)

    def fake_validate(config, repo_root=None):
        calls.append(("validate", repo_root))
        return True, None

    def fake_publish(repo, branch, issue, repo_root, pr_url=None):
        calls.append(("publish",))
        return "https://example.test/pr/1"

    monkeypatch.setattr("aiorchestra.pipeline.implement", fake_implement)
    monkeypatch.setattr("aiorchestra.pipeline.validate", fake_validate)
    monkeypatch.setattr("aiorchestra.pipeline.publish", fake_publish)

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
    )

    assert not pipeline._process_issue({"number": 10, "title": "Ghost changes"})

    # Only one implement call — aborted immediately, no retries
    assert calls == [
        ("implement", "implement", None, str(tmp_path)),
    ]


def test_publish_refuses_empty_branch(monkeypatch, tmp_path):
    """Invariants 3 & 4: never push or create a PR with zero commits ahead."""
    from aiorchestra.stages import publish as pub_mod

    push_called = False

    def fake_run(cmd, *, cwd=None, check=False, shell=None, logger=None):
        nonlocal push_called
        cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)

        if "status --porcelain" in cmd_str:
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if "log origin/main..HEAD" in cmd_str:
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if "push" in cmd_str:
            push_called = True
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pub_mod, "run_command", fake_run)

    from aiorchestra.stages.publish import publish

    result = publish(
        repo="owner/repo",
        branch="claude/99",
        issue={"number": 99, "title": "Empty"},
        repo_root=str(tmp_path),
    )

    assert result is None
    assert not push_called


def test_publish_aborts_on_git_error(monkeypatch, tmp_path):
    """Publish must abort immediately if git operations fail."""
    from aiorchestra.stages import publish as pub_mod

    push_called = False

    def fake_run(cmd, *, cwd=None, check=False, shell=None, logger=None):
        nonlocal push_called
        cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)

        if "status --porcelain" in cmd_str:
            return types.SimpleNamespace(returncode=128, stdout="", stderr="fatal: not a git repo")
        if "push" in cmd_str:
            push_called = True
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pub_mod, "run_command", fake_run)

    from aiorchestra.stages.publish import publish

    result = publish(
        repo="owner/repo",
        branch="claude/99",
        issue={"number": 99, "title": "Broken"},
        repo_root=str(tmp_path),
    )

    assert result is None
    assert not push_called


def test_invoke_claude_refuses_without_permissions(monkeypatch, caplog):
    """Invariant 1: never invoke an agent that cannot write files.

    With skip_permissions=False and no allowed_tools, the CLI must refuse
    to run and return failure — not just warn and proceed.
    """
    from aiorchestra.ai import ClaudeCodeProvider

    cli_invoked = False

    def spy_run(*a, **kw):
        nonlocal cli_invoked
        cli_invoked = True
        return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("aiorchestra.ai._cli.subprocess.run", spy_run)

    provider = ClaudeCodeProvider({"skip_permissions": False})

    with caplog.at_level(logging.ERROR, logger="aiorchestra.ai._claude_code"):
        result = provider.run("test prompt")

    assert result.success is False
    assert not cli_invoked
    assert any("no file-editing permissions" in r.message for r in caplog.records)


def test_claim_and_process_adds_awaiting_review_on_success(monkeypatch, tmp_path):
    """Sequential mode: success should swap agent-working for awaiting-review."""
    label_calls = []

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
    monkeypatch.setattr(
        "aiorchestra.pipeline.implement",
        lambda issue, config, prompt_name="implement", error_text=None, repo_root=None, osint_context="", repo=None: (
            InvokeResult(success=True)
        ),
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.validate", lambda config, repo_root=None: (True, None)
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.publish",
        lambda repo, branch, issue, repo_root, pr_url=None: "https://example.test/pr/1",
    )

    def fake_add(repo, number, label):
        label_calls.append(("add", label))
        return True

    def fake_remove(repo, number, label):
        label_calls.append(("remove", label))
        return True

    monkeypatch.setattr("aiorchestra.pipeline.add_label", fake_add)
    monkeypatch.setattr("aiorchestra.pipeline.remove_label", fake_remove)
    monkeypatch.setattr(
        "aiorchestra.pipeline.swap_label",
        lambda repo, n, rm, add: (fake_remove(repo, n, rm), fake_add(repo, n, add)),
    )

    pipeline = Pipeline(repo="owner/repo", label="claude", config={}, parallel=False)
    result = pipeline._claim_and_process({"number": 1, "title": "Test"})

    assert result is True
    assert ("add", "agent-working") in label_calls
    assert ("remove", "agent-working") in label_calls
    assert ("add", "awaiting-review") in label_calls


def test_claim_and_process_adds_agent_failed_on_failure(monkeypatch, tmp_path):
    """Sequential mode: failure should swap agent-working for agent-failed."""
    label_calls = []

    monkeypatch.setattr(
        "aiorchestra.pipeline.prepare_environment",
        lambda repo, branch, workspace: None,
    )
    monkeypatch.setattr("aiorchestra.pipeline.enrich_issue", lambda issue, config: "")

    def fake_add(repo, number, label):
        label_calls.append(("add", label))
        return True

    def fake_remove(repo, number, label):
        label_calls.append(("remove", label))
        return True

    monkeypatch.setattr("aiorchestra.pipeline.add_label", fake_add)
    monkeypatch.setattr("aiorchestra.pipeline.remove_label", fake_remove)
    monkeypatch.setattr(
        "aiorchestra.pipeline.swap_label",
        lambda repo, n, rm, add: (fake_remove(repo, n, rm), fake_add(repo, n, add)),
    )

    pipeline = Pipeline(repo="owner/repo", label="claude", config={}, parallel=False)
    result = pipeline._claim_and_process({"number": 2, "title": "Fail test"})

    assert result is False
    assert ("add", "agent-working") in label_calls
    assert ("remove", "agent-working") in label_calls
    assert ("add", "agent-failed") in label_calls
    assert ("add", "awaiting-review") not in label_calls


def test_rework_mode_used_when_branch_has_existing_work(monkeypatch, tmp_path):
    """Pipeline uses 'rework' prompt when branch already has commits vs origin/main."""
    calls: list[tuple] = []

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
    monkeypatch.setattr("aiorchestra.pipeline._branch_has_existing_work", lambda repo_root: True)
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
        calls.append(("implement", prompt_name))
        return InvokeResult(success=True)

    monkeypatch.setattr("aiorchestra.pipeline.implement", fake_implement)
    monkeypatch.setattr(
        "aiorchestra.pipeline.validate", lambda config, repo_root=None: (True, None)
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.publish",
        lambda repo, branch, issue, repo_root, pr_url=None: "https://example.test/pr/1",
    )

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
    )

    assert pipeline._process_issue({"number": 24, "title": "Rework me"}) is True
    assert calls == [("implement", "rework")]


def test_implement_mode_used_when_branch_has_no_existing_work(monkeypatch, tmp_path):
    """Pipeline uses 'implement' prompt when branch has no commits vs origin/main."""
    calls: list[tuple] = []

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
    monkeypatch.setattr("aiorchestra.pipeline._branch_has_existing_work", lambda repo_root: False)
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
        calls.append(("implement", prompt_name))
        return InvokeResult(success=True)

    monkeypatch.setattr("aiorchestra.pipeline.implement", fake_implement)
    monkeypatch.setattr(
        "aiorchestra.pipeline.validate", lambda config, repo_root=None: (True, None)
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.publish",
        lambda repo, branch, issue, repo_root, pr_url=None: "https://example.test/pr/1",
    )

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
    )

    assert pipeline._process_issue({"number": 11, "title": "Fresh issue"}) is True
    assert calls == [("implement", "implement")]


def test_review_fix_triggers_ci_recheck(monkeypatch, tmp_path):
    """After a review-fix publish, CI must be re-checked and failures remediated."""
    calls: list[tuple] = []
    # Initial validation passes, then review-fix validation passes,
    # then CI-fix validation passes.
    validate_results = iter([(True, None), (True, None), (True, None)])
    # First CI check (after initial publish) passes.
    # Second CI check (after review-fix publish) fails, then passes after fix.
    ci_results = iter([(True, None), (False, "lint error"), (True, None)])
    # Review fails once, then passes.
    review_results = iter([(False, "needs refactor"), (True, None)])

    monkeypatch.setattr(
        "aiorchestra.pipeline.prepare_environment",
        lambda repo, branch, workspace: str(tmp_path),
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.load_config",
        lambda path, repo_root=None: {
            "ai": {"max_retries": 3},
            "ci": {"enabled": True},
            "review": {"enabled": True},
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
        calls.append(("implement", prompt_name, error_text))
        return InvokeResult(success=True)

    def fake_validate(config, repo_root=None):
        calls.append(("validate",))
        return next(validate_results)

    def fake_publish(repo, branch, issue, repo_root, pr_url=None):
        calls.append(("publish",))
        return pr_url or "https://example.test/pr/1"

    def fake_wait_for_ci(pr_url, config):
        calls.append(("wait_for_ci",))
        return next(ci_results)

    def fake_review(repo, branch, config, issue=None, repo_root=None):
        calls.append(("review",))
        return next(review_results)

    monkeypatch.setattr("aiorchestra.pipeline.implement", fake_implement)
    monkeypatch.setattr("aiorchestra.pipeline.validate", fake_validate)
    monkeypatch.setattr("aiorchestra.pipeline.publish", fake_publish)
    monkeypatch.setattr("aiorchestra.pipeline.wait_for_ci", fake_wait_for_ci)
    monkeypatch.setattr("aiorchestra.pipeline.review", fake_review)

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
    )

    assert pipeline._process_issue({"number": 38, "title": "Review CI recheck"}) is True

    assert calls == [
        # Initial implementation + validation + publish
        ("implement", "implement", None),
        ("validate",),
        ("publish",),
        # Initial CI check passes
        ("wait_for_ci",),
        # Review fails → fix → validate → publish
        ("review",),
        ("implement", "fix_review", "needs refactor"),
        ("validate",),
        ("publish",),
        # Post-publish CI gate: CI fails → fix → validate → publish → CI passes
        ("wait_for_ci",),
        ("implement", "fix_ci", "lint error"),
        ("validate",),
        ("publish",),
        ("wait_for_ci",),
        # Review passes
        ("review",),
    ]


def test_review_fix_ci_failure_fails_issue(monkeypatch, tmp_path):
    """If CI fails after review-fix and cannot be remediated, the issue fails."""
    validate_results = iter([(True, None), (True, None), (True, None), (True, None), (True, None)])
    # Initial CI passes, post-review-fix CI always fails.
    ci_results = iter(
        [(True, None), (False, "ci broke"), (False, "ci broke"), (False, "ci broke")]
    )
    review_results = iter([(False, "fix needed")])

    monkeypatch.setattr(
        "aiorchestra.pipeline.prepare_environment",
        lambda repo, branch, workspace: str(tmp_path),
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.load_config",
        lambda path, repo_root=None: {
            "ai": {"max_retries": 3},
            "ci": {"enabled": True},
            "review": {"enabled": True},
        },
    )
    monkeypatch.setattr("aiorchestra.pipeline._has_changes", lambda repo_root: True)
    monkeypatch.setattr("aiorchestra.pipeline.enrich_issue", lambda issue, config: "")
    monkeypatch.setattr(
        "aiorchestra.pipeline.implement",
        lambda issue, config, prompt_name="implement", error_text=None, repo_root=None, osint_context="", repo=None: InvokeResult(
            success=True
        ),
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.validate",
        lambda config, repo_root=None: next(validate_results),
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.publish",
        lambda repo, branch, issue, repo_root, pr_url=None: pr_url
        or "https://example.test/pr/1",
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.wait_for_ci",
        lambda pr_url, config: next(ci_results),
    )
    monkeypatch.setattr(
        "aiorchestra.pipeline.review",
        lambda repo, branch, config, issue=None, repo_root=None: next(review_results),
    )

    pipeline = Pipeline(
        repo="owner/repo",
        label="claude",
        config={"ai": {"provider": "claude-code"}},
    )

    # Should fail because CI can't be fixed after the review-fix publish
    assert pipeline._process_issue({"number": 39, "title": "CI unfixable"}) is False


def test_prepare_fails_on_low_disk_space(monkeypatch, tmp_path):
    """Preparation must refuse to proceed when disk space is too low."""
    from aiorchestra.stages import prepare as prep_mod
    from aiorchestra.stages.prepare import prepare_environment

    fake_usage = types.SimpleNamespace(
        total=500 * 1024 * 1024,
        used=490 * 1024 * 1024,
        free=10 * 1024 * 1024,
    )
    monkeypatch.setattr(prep_mod.shutil, "disk_usage", lambda _path: fake_usage)

    result = prepare_environment("owner/repo", "claude/1", workspace=str(tmp_path))

    assert result is None
