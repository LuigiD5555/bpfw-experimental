---
name: bpfw-inspect
description: Locate Blueprint-owned source artifacts and inspect exact source windows.
---
# BPFW Inspect

Use `bpfw inspector` for logical metadata plus physical source windows. Concept blocks may own multiple artifacts; use `src N` to switch between code, tests, prompts, config, specs, or skills.

Use `bpfw trace PATH:LINE --json` when a physical location is known. Avoid reading whole files if BPFW can resolve the owning artifact/span first.
