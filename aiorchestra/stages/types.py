"""Shared types for the pipeline's stage roles.

The pipeline uses a few distinct stage contracts rather than one generic
``Stage.run()`` interface:

- implement stages return an ``InvokeResult`` carrying success/failure
  *and* optional clarification metadata.
- validation and remote-check stages return ``(passed, feedback)`` so the
  pipeline can feed failure output back into remediation prompts.
- publish stages return a PR URL once local changes have been committed and
  pushed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, TypeAlias, TypedDict

if TYPE_CHECKING:
    from aiorchestra.ai.claude import InvokeResult


class _RequiredIssueData(TypedDict):
    number: int
    title: str


class IssueData(_RequiredIssueData, total=False):
    """Minimal issue shape shared across stages and prompt rendering."""

    body: str
    labels: list[str]
    assignees: list[str]


PipelineConfig: TypeAlias = dict[str, Any]
FeedbackResult: TypeAlias = tuple[bool, str | None]
PublishResult: TypeAlias = str | None


class ImplementFn(Protocol):
    def __call__(
        self,
        issue: IssueData,
        config: PipelineConfig,
        prompt_name: str = "implement",
        error_text: str | None = None,
        repo_root: str | None = None,
    ) -> InvokeResult: ...


class ValidationFn(Protocol):
    def __call__(
        self,
        config: PipelineConfig,
        repo_root: str | None = None,
    ) -> FeedbackResult: ...


class RemoteCheckFn(Protocol):
    def __call__(self, pr_url: str) -> FeedbackResult: ...


class PublishFn(Protocol):
    def __call__(
        self,
        repo: str,
        branch: str,
        issue: IssueData,
        repo_root: str,
        pr_url: str | None = None,
    ) -> PublishResult: ...
