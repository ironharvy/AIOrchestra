"""Shared test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _mock_ensure_labels(monkeypatch):
    """Prevent ensure_labels from shelling out to ``gh`` in all tests."""

    def noop(repo, labels=None, dry_run=False):
        return []

    monkeypatch.setattr("aiorchestra.stages.labels.ensure_labels", noop)
    monkeypatch.setattr("aiorchestra.pipeline.ensure_labels", noop)
