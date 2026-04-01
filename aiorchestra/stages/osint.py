"""OSINT enrichment stage — gather external intelligence before implementation.

Runs shell-based OSINT tools (whois, dig, nmap, etc.) and optionally
summarises the raw output via a local Ollama model.  The result is a
structured context string that gets injected into the implementation prompt.

This stage spends zero cloud AI tokens — all inference happens locally.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field

from aiorchestra.ai.ollama import invoke_ollama, ollama_available
from aiorchestra.stages._shell import run_command
from aiorchestra.stages.types import IssueData
from aiorchestra.templates import render_template

log = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Built-in OSINT collectors
# ------------------------------------------------------------------


@dataclass(frozen=True)
class CollectorResult:
    """Output of a single OSINT collector."""

    name: str
    target: str
    raw: str
    success: bool


@dataclass
class OsintReport:
    """Aggregated results from all collectors, optionally summarised."""

    results: list[CollectorResult] = field(default_factory=list)
    summary: str = ""

    @property
    def has_data(self) -> bool:
        return any(r.success for r in self.results)

    def raw_text(self) -> str:
        """Concatenate successful collector outputs into a single block."""
        parts: list[str] = []
        for r in self.results:
            if r.success and r.raw.strip():
                parts.append(f"--- {r.name} ({r.target}) ---\n{r.raw.strip()}")
        return "\n\n".join(parts)

    def context_for_prompt(self) -> str:
        """Return the best available context: summary if present, else raw."""
        return self.summary or self.raw_text()


# Regex to extract targets (domains, IPs) from issue text.
_DOMAIN_RE = re.compile(
    r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)"
    r"+[a-zA-Z]{2,}\b"
)
_IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)

# Domains to ignore when extracting targets from issue text.
_IGNORE_DOMAINS = frozenset(
    {
        "github.com",
        "example.com",
        "example.org",
        "example.net",
        "localhost",
        "google.com",
        "githubusercontent.com",
    }
)


def extract_targets(text: str) -> list[str]:
    """Pull potential OSINT targets (domains, IPs) from free-form text."""
    targets: list[str] = []
    seen: set[str] = set()
    for match in _DOMAIN_RE.finditer(text):
        domain = match.group(0).lower()
        if domain not in seen and domain not in _IGNORE_DOMAINS:
            seen.add(domain)
            targets.append(domain)
    for match in _IPV4_RE.finditer(text):
        ip = match.group(0)
        if ip not in seen:
            seen.add(ip)
            targets.append(ip)
    return targets


# ------------------------------------------------------------------
# Individual collectors (each wraps one shell tool)
# ------------------------------------------------------------------


def _run_collector(
    name: str,
    cmd: list[str],
    target: str,
    timeout: int = 30,
) -> CollectorResult:
    """Execute a single OSINT tool and capture its output."""
    binary = cmd[0]
    if not shutil.which(binary):
        log.debug("Skipping %s — %s not found on PATH", name, binary)
        return CollectorResult(name=name, target=target, raw="", success=False)

    result = run_command(cmd, logger=log)
    if result.returncode != 0:
        log.warning("%s failed for %s: %s", name, target, result.stderr.strip())
        return CollectorResult(
            name=name,
            target=target,
            raw=result.stderr,
            success=False,
        )
    return CollectorResult(
        name=name,
        target=target,
        raw=result.stdout,
        success=True,
    )


def collect_whois(target: str) -> CollectorResult:
    return _run_collector("whois", ["whois", target], target)


def collect_dig(target: str) -> CollectorResult:
    return _run_collector("dig", ["dig", "+short", target], target)


def collect_dig_mx(target: str) -> CollectorResult:
    return _run_collector("dig-mx", ["dig", "+short", "MX", target], target)


def collect_dig_ns(target: str) -> CollectorResult:
    return _run_collector("dig-ns", ["dig", "+short", "NS", target], target)


def collect_dig_txt(target: str) -> CollectorResult:
    return _run_collector("dig-txt", ["dig", "+short", "TXT", target], target)


def collect_nmap_quick(target: str) -> CollectorResult:
    return _run_collector(
        "nmap-quick",
        ["nmap", "-T4", "-F", "--open", target],
        target,
        timeout=60,
    )


def collect_host(target: str) -> CollectorResult:
    return _run_collector("host", ["host", target], target)


def collect_curl_headers(target: str) -> CollectorResult:
    return _run_collector(
        "http-headers",
        ["curl", "-sI", "-m", "10", f"https://{target}"],
        target,
    )


# Registry mapping collector names to functions.
COLLECTORS: dict[str, callable] = {
    "whois": collect_whois,
    "dig": collect_dig,
    "dig-mx": collect_dig_mx,
    "dig-ns": collect_dig_ns,
    "dig-txt": collect_dig_txt,
    "host": collect_host,
    "http-headers": collect_curl_headers,
    "nmap-quick": collect_nmap_quick,
}

# Default collectors (safe, fast, no auth required).
DEFAULT_COLLECTORS = ["whois", "dig", "dig-mx", "dig-ns", "dig-txt", "host", "http-headers"]


# ------------------------------------------------------------------
# Orchestration
# ------------------------------------------------------------------


def _pick_collectors(osint_config: dict) -> list[str]:
    """Determine which collectors to run from config."""
    enabled = osint_config.get("collectors", DEFAULT_COLLECTORS)
    if isinstance(enabled, str):
        enabled = [c.strip() for c in enabled.split(",")]
    return [c for c in enabled if c in COLLECTORS]


def gather(
    targets: list[str],
    osint_config: dict,
) -> OsintReport:
    """Run configured OSINT collectors against all targets.

    Returns an ``OsintReport`` with raw results and (optionally) a
    summary produced by a local Ollama model.
    """
    if not targets:
        log.info("OSINT: no targets found — skipping")
        return OsintReport()

    collector_names = _pick_collectors(osint_config)
    if not collector_names:
        log.warning("OSINT: no valid collectors configured")
        return OsintReport()

    log.info(
        "OSINT: gathering data for %d target(s) with %d collector(s)",
        len(targets),
        len(collector_names),
    )

    report = OsintReport()
    for target in targets:
        for name in collector_names:
            collector_fn = COLLECTORS[name]
            result = collector_fn(target)
            report.results.append(result)
            if result.success:
                log.info("  %s(%s): OK (%d bytes)", name, target, len(result.raw))

    if not report.has_data:
        log.warning("OSINT: all collectors returned empty — nothing to summarise")
        return report

    # Summarise via local Ollama if configured and reachable.
    ollama_cfg = osint_config.get("ollama", {})
    if ollama_cfg.get("enabled", True) and ollama_available(ollama_cfg):
        report.summary = _summarise(report.raw_text(), ollama_cfg)
    else:
        log.info("OSINT: Ollama unavailable — using raw collector output")

    return report


def _summarise(raw_text: str, ollama_config: dict) -> str:
    """Distill raw OSINT output into a structured summary via Ollama."""
    prompt = render_template("osint_summarize", raw_osint=raw_text)
    result = invoke_ollama(prompt, ollama_config)
    if result:
        log.info("OSINT: summarised %d bytes → %d bytes", len(raw_text), len(result))
        return result
    log.warning("OSINT: summarisation failed — falling back to raw output")
    return ""


# ------------------------------------------------------------------
# Stage entry point (called by the pipeline)
# ------------------------------------------------------------------


def enrich_issue(
    issue: IssueData,
    osint_config: dict,
) -> str:
    """Extract targets from an issue and return OSINT context for the prompt.

    Returns an empty string if OSINT is disabled or produces no data.
    """
    if not osint_config.get("enabled", False):
        return ""

    text = f"{issue['title']}\n{issue.get('body', '')}"
    targets = osint_config.get("targets", []) or extract_targets(text)
    if not targets:
        log.info("OSINT: no targets identified in issue #%d", issue["number"])
        return ""

    log.info("OSINT: targets for issue #%d: %s", issue["number"], targets)
    report = gather(targets, osint_config)
    return report.context_for_prompt()
