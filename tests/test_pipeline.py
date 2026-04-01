"""Tests for pipeline orchestration."""

import os

from aiorchestra.pipeline import Pipeline


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

    def fake_implement(issue, config, prompt_name="implement", error_text=None, repo_root=None):
        calls.append(("implement", prompt_name, error_text, repo_root))
        return True

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

    def fake_implement(issue, config, prompt_name="implement", error_text=None, repo_root=None):
        calls.append(("implement", prompt_name, error_text, repo_root))
        return True

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
