# Blueprint Framework (BPFW)

Blueprint Framework (BPFW) is an AI-oriented architecture governance framework extracted from a RAG project.

This repository contains only the framework code (no application/domain code from the original project).

## What it provides

- Architecture checks
- Runtime contract validation
- Catalog governance and locking utilities
- Executable catalog validation
- Unified CLI for governance operations

## Install (editable)

```bash
pip install -e .
```

## CLI

```bash
bpfw check-architecture
bpfw validate-migration
bpfw preflight
bpfw check-executables
bpfw status
bpfw lock
bpfw unlock
```

## Project root resolution

When running BPFW against another project, point it to that project root:

```bash
export BPFW_PROJECT_ROOT=/path/to/target-project
```

The target project must contain `src/catalog/responsibilities`.

## Notes

- Internal Python package path is `bpfw`.
- Distribution/package name is `blueprint-framework` and CLI command is `bpfw`.
