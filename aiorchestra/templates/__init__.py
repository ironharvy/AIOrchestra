"""Template loader with two-layer resolution.

Resolution order (first found wins):
  1. {target_repo}/.aiorchestra/templates/{name}.md
  2. {aiorchestra}/templates/{name}.md  (built-in defaults)
"""

from pathlib import Path

_BUILTIN_DIR = Path(__file__).parent


def load_template(name: str, repo_root: str | None = None) -> str:
    """Load a template by name, checking repo overrides first.

    Args:
        name: Template name without extension (e.g. "implement").
        repo_root: Path to the target repo root. If provided, checks
                   {repo_root}/.aiorchestra/templates/ first.

    Returns:
        The template string with {placeholders} ready for .format().

    Raises:
        FileNotFoundError: If the template doesn't exist anywhere.
    """
    filename = f"{name}.md"

    # Check repo override first
    if repo_root:
        override = Path(repo_root) / ".aiorchestra" / "templates" / filename
        if override.exists():
            return override.read_text()

    # Fall back to built-in
    builtin = _BUILTIN_DIR / filename
    if builtin.exists():
        return builtin.read_text()

    raise FileNotFoundError(f"Template '{name}' not found")


def render_template(name: str, repo_root: str | None = None, **kwargs) -> str:
    """Load and render a template with the given variables."""
    template = load_template(name, repo_root)
    return template.format(**kwargs)
