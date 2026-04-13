"""Optional Langfuse integration for LLM tracing.

All public functions are safe to call regardless of whether ``langfuse`` is
installed — they degrade to no-ops when the SDK is absent or unconfigured.

See ``think_tank/adr-002-observability-strategy.md`` for the rationale.

A typical pipeline use:

    from aiorchestra import _langfuse

    _langfuse.init(config)
    trace_id = _langfuse.start_trace(
        name="issue-42",
        metadata={"repo": "owner/repo", "issue_number": 42},
        tags=["issue:42"],
    )
    _langfuse.set_current_trace(trace_id)

    # ... AI calls via providers happen here; they read the current trace ...

    _langfuse.end_trace(trace_id)
    _langfuse.flush()
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_initialized = False
_client = None
_current_trace_id: str | None = None

try:
    from langfuse import Langfuse

    _HAS_SDK = True
except ImportError:  # pragma: no cover
    _HAS_SDK = False
    Langfuse = None  # type: ignore[assignment,misc]


# Secrets that must never be sent to Langfuse. The privacy guard test asserts
# that these substrings don't appear in any recorded payload.
_SECRET_ENV_VARS = ("GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")


def _redact(text: str | None) -> str:
    """Remove any known-secret values from *text* before recording."""
    if not text:
        return text or ""
    for var in _SECRET_ENV_VARS:
        value = os.environ.get(var, "")
        if value and value in text:
            text = text.replace(value, f"***{var}***")
    return text


def init(config: dict) -> None:
    """Initialise the Langfuse client from *config*.

    Keys are resolved in order:
      1. ``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY`` env vars
      2. ``langfuse.public_key`` / ``langfuse.secret_key`` config keys

    Host is resolved similarly via ``LANGFUSE_HOST`` / ``langfuse.host``.

    The integration is disabled unless ``langfuse.enabled`` is truthy OR the
    env vars are set (env-var presence implies opt-in).

    Idempotent: a second call is a no-op.
    """
    global _initialized, _client
    if _initialized:
        return

    cfg = config.get("langfuse", {})
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "") or cfg.get("public_key", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "") or cfg.get("secret_key", "")
    host = os.environ.get("LANGFUSE_HOST", "") or cfg.get("host", "https://cloud.langfuse.com")

    # Opt-in: either explicit config toggle or env-var presence.
    enabled_by_config = bool(cfg.get("enabled"))
    enabled_by_env = bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")
    )
    if not (enabled_by_config or enabled_by_env):
        return

    if not _HAS_SDK:
        log.info("Langfuse enabled but SDK not installed; skipping")
        return

    if not (public_key and secret_key):
        log.warning("Langfuse enabled but keys missing; skipping")
        return

    _client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
    _initialized = True
    log.debug("Langfuse initialised (host=%s)", host)


def start_trace(
    name: str,
    *,
    metadata: dict | None = None,
    tags: list[str] | None = None,
) -> str:
    """Create a trace and return its id. Returns empty string when disabled."""
    if not _initialized or _client is None:
        return ""
    trace = _client.trace(name=name, metadata=metadata or {}, tags=tags or [])
    return getattr(trace, "id", "") or ""


def end_trace(
    trace_id: str,
    *,
    metadata: dict | None = None,
    status: str | None = None,
) -> None:
    """Mark a trace as finished. No-op when disabled or id empty."""
    if not _initialized or _client is None or not trace_id:
        return
    update_kwargs: dict = {}
    if metadata:
        update_kwargs["metadata"] = metadata
    if status:
        update_kwargs["metadata"] = {**update_kwargs.get("metadata", {}), "status": status}
    # Langfuse's trace update API varies; we attempt a best-effort call.
    try:
        _client.trace(id=trace_id, **update_kwargs)
    except Exception as exc:  # pragma: no cover
        log.debug("Langfuse end_trace failed: %s", exc)


def record_generation(
    *,
    name: str,
    model: str,
    provider: str,
    prompt: str,
    completion: str,
    start_time,
    end_time,
    success: bool,
    trace_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Record a single LLM generation (one provider invocation).

    Prompt and completion are redacted for known secret env vars before being
    sent. Safe to call when Langfuse is disabled (no-op).
    """
    if not _initialized or _client is None:
        return

    effective_trace_id = trace_id or _current_trace_id
    safe_metadata = dict(metadata or {})
    safe_metadata.setdefault("provider", provider)
    safe_metadata.setdefault("success", success)

    try:
        _client.generation(
            trace_id=effective_trace_id or None,
            name=name,
            model=model,
            input=_redact(prompt),
            output=_redact(completion),
            start_time=start_time,
            end_time=end_time,
            metadata=safe_metadata,
            level="DEFAULT" if success else "ERROR",
        )
    except Exception as exc:  # pragma: no cover
        log.debug("Langfuse record_generation failed: %s", exc)


def set_current_trace(trace_id: str | None) -> None:
    """Set the module-level current trace id so providers can attach to it.

    Uses a module global — fine for the current pipeline model because child
    processes (forked for parallel mode) each have their own address space.
    """
    global _current_trace_id
    _current_trace_id = trace_id


def current_trace_id() -> str | None:
    """Return the current trace id, if any."""
    return _current_trace_id


def flush(timeout: float = 2.0) -> None:
    """Block until queued events are sent, up to *timeout* seconds.

    MUST be called before ``os._exit`` in forked children — the SDK flushes
    asynchronously and events are lost if the process exits abruptly.
    """
    if not _initialized or _client is None:
        return
    try:
        _client.flush()  # Langfuse flush doesn't take a timeout; param kept for API symmetry
    except Exception as exc:  # pragma: no cover
        log.debug("Langfuse flush failed: %s", exc)
