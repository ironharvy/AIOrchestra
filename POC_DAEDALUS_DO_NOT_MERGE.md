# ⚠️ PoC branch — do not merge, do not delete

This branch (`claude/daedalus-dspy-poc-WBs5e`) carries experimental
changes to AIOrchestra needed by the DaedalusDSPy proof-of-concept.

See `ironharvy/DaedalusDSPy` → `POC.md` on the matching branch for
context and rationale.

**Before merging or deleting this branch:** confirm the PoC is either
abandoned or graduated into a proper design. Do not clean this up on
autopilot.

Current experimental changes on this branch:

- `aiorchestra/templates/implement.md` — softened from coder-only wording
  to a role-agnostic prompt that accepts documentation-only deliverables.
  This is required so non-coding roles (CEO, BA, PM, etc.) can satisfy
  the pipeline's "must produce a diff" invariant by committing markdown
  artifacts under `docs/`.
