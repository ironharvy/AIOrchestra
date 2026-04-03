"""Core abstractions for the AI provider layer.

Defines :class:`InvokeResult` (the universal return type), the
:func:`_parse_clarification` helper, and the :class:`AIProvider` ABC that
every backend must implement.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

log = logging.getLogger(__name__)

_CLARIFICATION_RE = re.compile(
    r"^NEEDS_CLARIFICATION:\s*(.+)",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class InvokeResult:
    """Structured outcome of an AI invocation."""

    success: bool
    output: str = ""
    needs_clarification: bool = False
    clarification_message: str = ""


def _parse_clarification(text: str) -> InvokeResult:
    """Check raw agent output for clarification requests."""
    match = _CLARIFICATION_RE.search(text)
    if match:
        return InvokeResult(
            success=True,
            output=text,
            needs_clarification=True,
            clarification_message=match.group(1).strip(),
        )
    return InvokeResult(success=True, output=text)


class AIProvider(ABC):
    """Uniform interface for all AI backends (Strategy pattern)."""

    def __init__(self, config: dict) -> None:
        self._config = config

    @abstractmethod
    def run(
        self,
        prompt: str,
        *,
        system: str | None = None,
        cwd: str | None = None,
    ) -> InvokeResult:
        """Send *prompt* to the backend and return a structured result."""

    def available(self) -> bool:  # noqa: PLR6301
        """Return True if the backend is reachable.  Override for health-checks."""
        return True
