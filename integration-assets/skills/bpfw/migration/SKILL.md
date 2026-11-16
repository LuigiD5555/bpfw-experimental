---
name: bpfw-migration
description: Keep Blueprint schema migrations deterministic and reviewable.
---
# BPFW Migration

Do not migrate many Blueprint shards by hand. Prefer versioned BPFW migration/batch operations, always with plan/apply and verification. After migration run `bpfw batch audit --json` and `bpfw verify`.
