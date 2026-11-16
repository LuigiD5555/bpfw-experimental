---
name: bpfw-batch
description: Use deterministic BPFW plan/apply operations for repetitive Blueprint changes.
---
# BPFW Batch

Prefer batch operations over manually rewriting multiple YAML blocks.

Useful commands:
- `bpfw batch generate-uids --json`
- `bpfw batch set --scope artifact --where type=code --field required --value true --json`
- `bpfw batch default ...`
- `bpfw batch remove ...`
- `bpfw batch rename-field ...`
- `bpfw batch replace-value ...`
- `bpfw batch move-path OLD NEW --json`

Mutations create a plan by default. Review its compact result, then apply with `bpfw batch apply PLAN_ID`. Do not bypass plan/apply for bulk changes.
