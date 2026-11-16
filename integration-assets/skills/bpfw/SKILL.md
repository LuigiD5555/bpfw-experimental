---
name: bpfw
description: Route Blueprint Framework work to the smallest deterministic workflow before using broad LLM context.
---
# BPFW Router

Load only the child skill needed for the request.

- Repeated/bulk metadata edits, UID generation, path moves: `batch/SKILL.md`
- Source window, code/prompt/config location, `src N`: `inspect/SKILL.md`
- Why/when/what changed, prior intent, traceability: `history/SKILL.md`
- Find unbound code/prompts/config/specs: `artifacts/SKILL.md`
- Blueprint schema/version upgrades: `migration/SKILL.md`
- Audit, normalize, compact, verify: `maintenance/SKILL.md`

Rule: if an operation is deterministic, run BPFW and consume its compact JSON before loading Blueprint files into the model.
