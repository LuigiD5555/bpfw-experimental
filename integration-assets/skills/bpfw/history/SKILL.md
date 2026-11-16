---
name: bpfw-history
description: Query recorded intent and change history without reconstructing it from source files.
---
# BPFW History

For why/when/previous-intent questions, query the ledger first:
- `bpfw history TARGET --json`
- `bpfw history search TERM --json`
- `bpfw why TARGET --json`
- `bpfw trace PATH:LINE --json`

Treat recorded events as authority. Do not infer unrecorded past intent from Git unless explicitly doing a labeled historical backfill.
