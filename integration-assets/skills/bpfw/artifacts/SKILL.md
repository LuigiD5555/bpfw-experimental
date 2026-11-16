---
name: bpfw-artifacts
description: Discover physical artifacts that are not yet bound to Blueprint intent.
---
# BPFW Artifacts

Run `bpfw batch discover-artifacts --unbound --json` before scanning the repository manually. Review only returned candidates.

BPFW may discover code units and high-confidence flow artifacts such as prompts/config/specs referenced by Go. Binding semantic ownership remains a human/LLM decision when ambiguous.
