"""Tests for the optional Sentry integration."""

from unittest.mock import MagicMock, patch

import aiorchestra._sentry as sentry_mod


def _reset():
    """Reset module-level state between tests."""
    sentry_mod._initialized = False


class TestInitNoSdk:
    """Behaviour when sentry-sdk is not installed."""

    def test_init_without_sdk(self):
        _reset()
        with patch.object(sentry_mod, "_HAS_SDK", False):
            sentry_mod.init({"sentry": {"dsn": "https://key@sentry.io/1"}})
        assert sentry_mod._initialized is False

    def test_noop_helpers_without_init(self):
        """All helpers should be safe to call when uninitialised."""
        _reset()
        sentry_mod.set_tag("key", "value")
        sentry_mod.set_context("ctx", {"a": 1})
        sentry_mod.add_breadcrumb(category="test", message="msg")
        sentry_mod.capture_exception(RuntimeError("boom"))
        sentry_mod.flush()


class TestInitIdempotent:
    """init() must be safe to call multiple times."""

    def test_second_init_is_noop(self):
        _reset()
        mock_sdk = MagicMock()
        with (
            patch.object(sentry_mod, "_HAS_SDK", True),
            patch.object(sentry_mod, "sentry_sdk", mock_sdk, create=True),
            patch.dict("os.environ", {}, clear=False),
        ):
            sentry_mod.init({"sentry": {"dsn": "https://key@sentry.io/1"}})
            sentry_mod.init({"sentry": {"dsn": "https://other@sentry.io/2"}})

        # Second call must NOT re-init (which would replace the hub and lose
        # accumulated tags/breadcrumbs).
        assert mock_sdk.init.call_count == 1


class TestTracesSampleRateEnv:
    """SENTRY_TRACES_SAMPLE_RATE env var overrides config."""

    def test_env_overrides_traces_sample_rate(self):
        _reset()
        mock_sdk = MagicMock()
        with (
            patch.object(sentry_mod, "_HAS_SDK", True),
            patch.object(sentry_mod, "sentry_sdk", mock_sdk, create=True),
            patch.dict(
                "os.environ",
                {
                    "SENTRY_DSN": "https://key@sentry.io/1",
                    "SENTRY_TRACES_SAMPLE_RATE": "0.25",
                },
            ),
        ):
            sentry_mod.init({"sentry": {"dsn": "", "traces_sample_rate": 0.0}})

        assert mock_sdk.init.call_args[1]["traces_sample_rate"] == 0.25

    def test_invalid_env_rate_falls_back_to_config(self):
        _reset()
        mock_sdk = MagicMock()
        with (
            patch.object(sentry_mod, "_HAS_SDK", True),
            patch.object(sentry_mod, "sentry_sdk", mock_sdk, create=True),
            patch.dict(
                "os.environ",
                {
                    "SENTRY_DSN": "https://key@sentry.io/1",
                    "SENTRY_TRACES_SAMPLE_RATE": "not-a-number",
                },
            ),
        ):
            sentry_mod.init({"sentry": {"dsn": "", "traces_sample_rate": 0.1}})

        assert mock_sdk.init.call_args[1]["traces_sample_rate"] == 0.1


class TestFlush:
    """flush() delegates to the SDK when initialised, no-op otherwise."""

    def test_flush_calls_sdk_when_initialised(self):
        _reset()
        mock_sdk = MagicMock()
        with (
            patch.object(sentry_mod, "_HAS_SDK", True),
            patch.object(sentry_mod, "sentry_sdk", mock_sdk, create=True),
            patch.dict("os.environ", {}, clear=False),
        ):
            sentry_mod.init({"sentry": {"dsn": "https://key@sentry.io/1"}})
            sentry_mod.flush(timeout=5.0)

        mock_sdk.flush.assert_called_once_with(5.0)


class TestInitWithSdk:
    """Behaviour when sentry-sdk is installed (mocked)."""

    def test_init_with_dsn_from_config(self):
        _reset()
        mock_sdk = MagicMock()
        with (
            patch.object(sentry_mod, "_HAS_SDK", True),
            patch.object(sentry_mod, "sentry_sdk", mock_sdk, create=True),
            patch.dict("os.environ", {}, clear=False),
        ):
            sentry_mod.init({"sentry": {"dsn": "https://key@sentry.io/1"}})

        assert sentry_mod._initialized is True
        mock_sdk.init.assert_called_once_with(
            dsn="https://key@sentry.io/1",
            environment="production",
            traces_sample_rate=0.0,
            send_default_pii=False,
        )

    def test_init_with_dsn_from_env(self):
        _reset()
        mock_sdk = MagicMock()
        with (
            patch.object(sentry_mod, "_HAS_SDK", True),
            patch.object(sentry_mod, "sentry_sdk", mock_sdk, create=True),
            patch.dict("os.environ", {"SENTRY_DSN": "https://env@sentry.io/2"}),
        ):
            sentry_mod.init({"sentry": {"dsn": "https://cfg@sentry.io/1"}})

        # Env var takes precedence over config.
        mock_sdk.init.assert_called_once()
        call_kwargs = mock_sdk.init.call_args[1]
        assert call_kwargs["dsn"] == "https://env@sentry.io/2"

    def test_env_overrides_environment(self):
        _reset()
        mock_sdk = MagicMock()
        with (
            patch.object(sentry_mod, "_HAS_SDK", True),
            patch.object(sentry_mod, "sentry_sdk", mock_sdk, create=True),
            patch.dict(
                "os.environ",
                {
                    "SENTRY_DSN": "https://key@sentry.io/1",
                    "SENTRY_ENVIRONMENT": "staging",
                },
            ),
        ):
            sentry_mod.init({"sentry": {"dsn": "", "environment": "production"}})

        call_kwargs = mock_sdk.init.call_args[1]
        assert call_kwargs["environment"] == "staging"

    def test_no_init_when_dsn_empty(self):
        _reset()
        mock_sdk = MagicMock()
        with (
            patch.object(sentry_mod, "_HAS_SDK", True),
            patch.object(sentry_mod, "sentry_sdk", mock_sdk, create=True),
            patch.dict("os.environ", {}, clear=False),
        ):
            sentry_mod.init({"sentry": {"dsn": ""}})

        assert sentry_mod._initialized is False
        mock_sdk.init.assert_not_called()

    def test_no_init_when_sentry_section_missing(self):
        _reset()
        mock_sdk = MagicMock()
        with (
            patch.object(sentry_mod, "_HAS_SDK", True),
            patch.object(sentry_mod, "sentry_sdk", mock_sdk, create=True),
            patch.dict("os.environ", {}, clear=False),
        ):
            sentry_mod.init({})

        assert sentry_mod._initialized is False
        mock_sdk.init.assert_not_called()


class TestHelpers:
    """Helpers delegate to SDK when initialised."""

    def _init_mock(self):
        _reset()
        mock_sdk = MagicMock()
        with (
            patch.object(sentry_mod, "_HAS_SDK", True),
            patch.object(sentry_mod, "sentry_sdk", mock_sdk, create=True),
            patch.dict("os.environ", {}, clear=False),
        ):
            sentry_mod.init({"sentry": {"dsn": "https://key@sentry.io/1"}})
        return mock_sdk

    def test_set_tag(self):
        mock_sdk = self._init_mock()
        with patch.object(sentry_mod, "sentry_sdk", mock_sdk, create=True):
            sentry_mod.set_tag("repo", "owner/repo")
        mock_sdk.set_tag.assert_called_once_with("repo", "owner/repo")

    def test_set_context(self):
        mock_sdk = self._init_mock()
        with patch.object(sentry_mod, "sentry_sdk", mock_sdk, create=True):
            sentry_mod.set_context("issue", {"number": 42})
        mock_sdk.set_context.assert_called_once_with("issue", {"number": 42})

    def test_add_breadcrumb(self):
        mock_sdk = self._init_mock()
        with patch.object(sentry_mod, "sentry_sdk", mock_sdk, create=True):
            sentry_mod.add_breadcrumb(category="stage", message="prepare done")
        mock_sdk.add_breadcrumb.assert_called_once_with(
            category="stage",
            message="prepare done",
            level="info",
        )

    def test_capture_exception(self):
        mock_sdk = self._init_mock()
        err = RuntimeError("boom")
        with patch.object(sentry_mod, "sentry_sdk", mock_sdk, create=True):
            sentry_mod.capture_exception(err)
        mock_sdk.capture_exception.assert_called_once_with(err)
