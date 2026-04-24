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

## External write safety

By default, write-like catalog operations are blocked when `BPFW_PROJECT_ROOT`
points to a different directory than the current working directory. This
prevents accidental catalog mutations in external projects.

To allow this intentionally, set:

```bash
export BPFW_ALLOW_EXTERNAL_CATALOG_WRITES=1
```

## Lock phases

`bpfw lock` is designed to protect in three phases:

- Phase 1 (edit access): catalog YAML files become read-only.
- Phase 2 (save): write/save attempts fail because files are read-only.
- Phase 3 (commit): pre-commit hook rejects catalog mutations while locked.

Implementation details:

- Lock backend is `linux_immutable` (`chattr +i`) and requires `sudo`.
- Unlock requires `sudo`; bypassing with internal non-sudo calls is rejected.
- `.catalog/lockstate.json` is hardened when locked and checked for tampering.

If immutable locking cannot be enforced, `bpfw lock` fails with error.

## Notes

- Internal Python package path is `bpfw`.
- Distribution/package name is `blueprint-framework` and CLI command is `bpfw`.
