"""Optional Sentry integration.

All public functions are safe to call regardless of whether ``sentry-sdk`` is
installed — they degrade to no-ops when the SDK is absent or unconfigured.

See ``think_tank/adr-002-observability-strategy.md`` for the rationale.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_initialized = False

try:
    import sentry_sdk

    _HAS_SDK = True
except ImportError:  # pragma: no cover
    _HAS_SDK = False


def init(config: dict) -> None:
    """Initialise the Sentry SDK from *config* (the full merged config dict).

    The DSN is resolved in order:
      1. ``SENTRY_DSN`` environment variable
      2. ``sentry.dsn`` config key

    Environment overrides:
      - ``SENTRY_ENVIRONMENT`` overrides ``sentry.environment``
      - ``SENTRY_TRACES_SAMPLE_RATE`` overrides ``sentry.traces_sample_rate``

    Does nothing when no DSN is available or when the SDK is not installed.
    Idempotent: a second call is a no-op (so multiple CLI subcommands calling
    this don't replace the hub and drop tags/breadcrumbs).
    """
    global _initialized
    if _initialized:
        return

    sentry_cfg = config.get("sentry", {})
    dsn = os.environ.get("SENTRY_DSN", "") or sentry_cfg.get("dsn", "")
    if not dsn or not _HAS_SDK:
        return

    environment = os.environ.get("SENTRY_ENVIRONMENT", "") or sentry_cfg.get(
        "environment", "production"
    )
    env_rate = os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "")
    if env_rate:
        try:
            traces_sample_rate = float(env_rate)
        except ValueError:
            log.warning("Invalid SENTRY_TRACES_SAMPLE_RATE=%r; falling back to config", env_rate)
            traces_sample_rate = sentry_cfg.get("traces_sample_rate", 0.0)
    else:
        traces_sample_rate = sentry_cfg.get("traces_sample_rate", 0.0)

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
    )
    _initialized = True
    log.debug("Sentry initialised (environment=%s)", environment)


def set_tag(key: str, value: str) -> None:
    """Set a Sentry tag on the current scope."""
    if _initialized:
        sentry_sdk.set_tag(key, value)


def set_context(name: str, data: dict) -> None:
    """Attach structured context to the current Sentry scope."""
    if _initialized:
        sentry_sdk.set_context(name, data)


def add_breadcrumb(*, category: str, message: str, level: str = "info") -> None:
    """Record a Sentry breadcrumb (trail of events leading to an error)."""
    if _initialized:
        sentry_sdk.add_breadcrumb(category=category, message=message, level=level)


def capture_exception(error: BaseException | None = None) -> None:
    """Send an exception to Sentry."""
    if _initialized:
        sentry_sdk.capture_exception(error)


def flush(timeout: float = 2.0) -> None:
    """Block until queued events are sent, up to *timeout* seconds.

    MUST be called before ``os._exit`` in forked children — Sentry's transport
    is asynchronous, so events are queued and lost if the process exits
    abruptly.
    """
    if _initialized:
        sentry_sdk.flush(timeout)
