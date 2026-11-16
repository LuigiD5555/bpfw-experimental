---
name: bpfw-maintenance
description: Run compact audits and deterministic cleanup before asking an LLM to inspect broad Blueprint context.
---
# BPFW Maintenance

Start with `bpfw batch audit --json`. It returns compact counts and samples.

Use:
- `bpfw normalize --json` for safe path/derivable-metadata cleanup.
- `bpfw compact --json` to propose reusable profiles for repeated artifact metadata.
- `bpfw verify` after applied changes.

Request `bpfw batch audit --json --details` only when the compact sample is insufficient.
