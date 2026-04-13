"""Tests for the optional Langfuse integration."""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

import pytest

from aiorchestra import _langfuse


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Reset module state between tests."""
    monkeypatch.setattr(_langfuse, "_initialized", False)
    monkeypatch.setattr(_langfuse, "_client", None)
    monkeypatch.setattr(_langfuse, "_current_trace_id", None)
    # Clear env vars that could auto-enable the integration.
    for var in (
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_HOST",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


class TestInitDisabledByDefault:
    def test_no_config_no_env_is_noop(self):
        _langfuse.init({})
        assert _langfuse._initialized is False
        assert _langfuse._client is None

    def test_enabled_false_is_noop(self):
        _langfuse.init({"langfuse": {"enabled": False}})
        assert _langfuse._initialized is False


class TestInitOptIn:
    def test_enabled_but_no_sdk_skips(self, monkeypatch):
        monkeypatch.setattr(_langfuse, "_HAS_SDK", False)
        _langfuse.init({"langfuse": {"enabled": True, "public_key": "pk", "secret_key": "sk"}})
        assert _langfuse._initialized is False

    def test_enabled_but_missing_keys_skips(self, monkeypatch):
        monkeypatch.setattr(_langfuse, "_HAS_SDK", True)
        monkeypatch.setattr(_langfuse, "Langfuse", MagicMock())
        _langfuse.init({"langfuse": {"enabled": True}})
        assert _langfuse._initialized is False

    def test_enabled_with_keys_initialises(self, monkeypatch):
        fake_client = MagicMock()
        fake_cls = MagicMock(return_value=fake_client)
        monkeypatch.setattr(_langfuse, "_HAS_SDK", True)
        monkeypatch.setattr(_langfuse, "Langfuse", fake_cls)
        _langfuse.init({"langfuse": {"enabled": True, "public_key": "pk", "secret_key": "sk"}})
        assert _langfuse._initialized is True
        assert _langfuse._client is fake_client
        fake_cls.assert_called_once_with(
            public_key="pk",
            secret_key="sk",
            host="https://cloud.langfuse.com",
        )

    def test_env_vars_enable_without_config_toggle(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "env-pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "env-sk")
        fake_cls = MagicMock()
        monkeypatch.setattr(_langfuse, "_HAS_SDK", True)
        monkeypatch.setattr(_langfuse, "Langfuse", fake_cls)
        _langfuse.init({})
        assert _langfuse._initialized is True
        fake_cls.assert_called_once_with(
            public_key="env-pk",
            secret_key="env-sk",
            host="https://cloud.langfuse.com",
        )

    def test_env_vars_take_precedence_over_config(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "env-pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "env-sk")
        fake_cls = MagicMock()
        monkeypatch.setattr(_langfuse, "_HAS_SDK", True)
        monkeypatch.setattr(_langfuse, "Langfuse", fake_cls)
        _langfuse.init(
            {
                "langfuse": {
                    "enabled": True,
                    "public_key": "cfg-pk",
                    "secret_key": "cfg-sk",
                }
            }
        )
        fake_cls.assert_called_once_with(
            public_key="env-pk",
            secret_key="env-sk",
            host="https://cloud.langfuse.com",
        )


class TestInitIdempotent:
    def test_second_init_is_noop(self, monkeypatch):
        fake_cls = MagicMock()
        monkeypatch.setattr(_langfuse, "_HAS_SDK", True)
        monkeypatch.setattr(_langfuse, "Langfuse", fake_cls)
        cfg = {"langfuse": {"enabled": True, "public_key": "pk", "secret_key": "sk"}}
        _langfuse.init(cfg)
        _langfuse.init(cfg)
        assert fake_cls.call_count == 1


class TestStartEndTrace:
    def test_disabled_returns_empty_string(self):
        assert _langfuse.start_trace("foo") == ""

    def test_enabled_returns_trace_id(self, monkeypatch):
        trace = MagicMock(id="trace-123")
        client = MagicMock()
        client.trace.return_value = trace
        monkeypatch.setattr(_langfuse, "_initialized", True)
        monkeypatch.setattr(_langfuse, "_client", client)

        tid = _langfuse.start_trace("issue-42", metadata={"k": "v"}, tags=["t"])

        assert tid == "trace-123"
        client.trace.assert_called_once_with(name="issue-42", metadata={"k": "v"}, tags=["t"])

    def test_end_trace_disabled_is_noop(self):
        _langfuse.end_trace("tid", status="success")  # must not raise

    def test_end_trace_calls_client(self, monkeypatch):
        client = MagicMock()
        monkeypatch.setattr(_langfuse, "_initialized", True)
        monkeypatch.setattr(_langfuse, "_client", client)
        _langfuse.end_trace("tid-1", status="success")
        client.trace.assert_called_once()
        kwargs = client.trace.call_args.kwargs
        assert kwargs["id"] == "tid-1"
        assert kwargs["metadata"]["status"] == "success"

    def test_end_trace_empty_id_is_noop(self, monkeypatch):
        client = MagicMock()
        monkeypatch.setattr(_langfuse, "_initialized", True)
        monkeypatch.setattr(_langfuse, "_client", client)
        _langfuse.end_trace("", status="success")
        client.trace.assert_not_called()


class TestRecordGeneration:
    def _ts(self):
        return dt.datetime(2026, 1, 1, 12, 0, 0), dt.datetime(2026, 1, 1, 12, 0, 1)

    def test_disabled_is_noop(self):
        start, end = self._ts()
        _langfuse.record_generation(
            name="n",
            model="m",
            provider="p",
            prompt="in",
            completion="out",
            start_time=start,
            end_time=end,
            success=True,
        )  # must not raise

    def test_records_with_explicit_trace_id(self, monkeypatch):
        client = MagicMock()
        monkeypatch.setattr(_langfuse, "_initialized", True)
        monkeypatch.setattr(_langfuse, "_client", client)
        start, end = self._ts()

        _langfuse.record_generation(
            name="claude.run",
            model="claude-opus-4-6",
            provider="claude-code",
            prompt="hello",
            completion="world",
            start_time=start,
            end_time=end,
            success=True,
            trace_id="trace-abc",
        )

        client.generation.assert_called_once()
        kwargs = client.generation.call_args.kwargs
        assert kwargs["trace_id"] == "trace-abc"
        assert kwargs["model"] == "claude-opus-4-6"
        assert kwargs["input"] == "hello"
        assert kwargs["output"] == "world"
        assert kwargs["level"] == "DEFAULT"
        assert kwargs["metadata"]["provider"] == "claude-code"
        assert kwargs["metadata"]["success"] is True

    def test_uses_current_trace_when_id_not_given(self, monkeypatch):
        client = MagicMock()
        monkeypatch.setattr(_langfuse, "_initialized", True)
        monkeypatch.setattr(_langfuse, "_client", client)
        _langfuse.set_current_trace("current-trace")
        start, end = self._ts()

        _langfuse.record_generation(
            name="n",
            model="m",
            provider="p",
            prompt="i",
            completion="o",
            start_time=start,
            end_time=end,
            success=True,
        )

        assert client.generation.call_args.kwargs["trace_id"] == "current-trace"

    def test_failure_sets_error_level(self, monkeypatch):
        client = MagicMock()
        monkeypatch.setattr(_langfuse, "_initialized", True)
        monkeypatch.setattr(_langfuse, "_client", client)
        start, end = self._ts()

        _langfuse.record_generation(
            name="n",
            model="m",
            provider="p",
            prompt="i",
            completion="err",
            start_time=start,
            end_time=end,
            success=False,
        )
        assert client.generation.call_args.kwargs["level"] == "ERROR"


class TestRedaction:
    """ADR-002 privacy guard: secrets must never appear in recorded payloads."""

    def _ts(self):
        return dt.datetime(2026, 1, 1), dt.datetime(2026, 1, 1)

    @pytest.mark.parametrize(
        "env_var", ["GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]
    )
    def test_known_secrets_redacted_from_prompt_and_completion(self, monkeypatch, env_var):
        secret = "s3cr3t-VALUE-xyz"
        monkeypatch.setenv(env_var, secret)
        client = MagicMock()
        monkeypatch.setattr(_langfuse, "_initialized", True)
        monkeypatch.setattr(_langfuse, "_client", client)
        start, end = self._ts()

        _langfuse.record_generation(
            name="n",
            model="m",
            provider="p",
            prompt=f"please use {secret} to auth",
            completion=f"ok used {secret}",
            start_time=start,
            end_time=end,
            success=True,
        )

        kwargs = client.generation.call_args.kwargs
        assert secret not in kwargs["input"]
        assert secret not in kwargs["output"]
        assert f"***{env_var}***" in kwargs["input"]
        assert f"***{env_var}***" in kwargs["output"]

    def test_redact_handles_empty_input(self):
        assert _langfuse._redact("") == ""
        assert _langfuse._redact(None) == ""

    def test_redact_no_env_vars_set_passes_through(self, monkeypatch):
        for var in ("GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        assert _langfuse._redact("nothing to redact here") == "nothing to redact here"


class TestCurrentTrace:
    def test_get_set_and_clear(self):
        assert _langfuse.current_trace_id() is None
        _langfuse.set_current_trace("t1")
        assert _langfuse.current_trace_id() == "t1"
        _langfuse.set_current_trace(None)
        assert _langfuse.current_trace_id() is None


class TestFlush:
    def test_disabled_is_noop(self):
        _langfuse.flush()  # must not raise

    def test_enabled_calls_client_flush(self, monkeypatch):
        client = MagicMock()
        monkeypatch.setattr(_langfuse, "_initialized", True)
        monkeypatch.setattr(_langfuse, "_client", client)
        _langfuse.flush()
        client.flush.assert_called_once()
