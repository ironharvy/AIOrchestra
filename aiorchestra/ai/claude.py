"""Claude AI provider — backward-compatibility shim.

The canonical implementation now lives in :mod:`aiorchestra.ai.provider`
(``ClaudeCodeProvider``).  This module re-exports the symbols that existing
call-sites and tests import so nothing breaks.
"""

from __future__ import annotations

from aiorchestra.ai.provider import (
    InvokeResult,
    _parse_clarification,
    create_provider,
)

__all__ = [
    "InvokeResult",
    "_parse_clarification",
    "invoke_claude",
    "_invoke_cli",
]


def invoke_claude(
    prompt: str,
    ai_config: dict,
    capture_output: bool = False,
    cwd: str | None = None,
) -> InvokeResult:
    """Invoke Claude Code CLI with the given prompt.

    Thin wrapper kept for backward compatibility — delegates to
    ``ClaudeCodeProvider.run()``.
    """
    provider = create_provider({**ai_config, "provider": "claude-code"})
    return provider.run(prompt, capture_output=capture_output, cwd=cwd)


# Alias kept for tests that import _invoke_cli directly.
_invoke_cli = invoke_claude
