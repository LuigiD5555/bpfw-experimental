# Blueprint Framework (BPFW)

Blueprint Framework (BPFW) is an MVP catalog control tool for Python projects.

This repository contains only the framework code (no application/domain code from the original project).

## What it provides

- `bpfw/blueprint.yaml` catalog generation
- Catalog validation against discovered Python code
- Drift detection for declared responsibilities
- Protected initialization with OS-level authority lock
- Repair flow for incomplete local protection
- Human-readable `verify` and `status` reports

## Install (editable)

```bash
pip install -e .
```

## CLI

```bash
bpfw init
bpfw wizard
bpfw inspect
bpfw plan
bpfw verify
bpfw status
bpfw lock
bpfw unlock
bpfw repair
```

## Project root resolution

When running BPFW against another project, point it to that project root:

```bash
bpfw verify --project-root /path/to/target-project
```

The target project may contain `bpfw/blueprint.yaml`. If it does not, run `bpfw init`.

## Authority Lock

`bpfw init` creates the blueprint and enables OS-level authority protection.
`bpfw lock` protects exactly:

```text
bpfw/blueprint.yaml
BPFW internal guard files
```

If an existing project has a broken lock state, run:

```bash
bpfw repair
```

`bpfw unlock` reverses the same protection for intentional authority edit
windows. There is no separate public protection setup flow.

## Notes

- Internal Python package path is `bpfw`.
- Distribution/package name is `blueprint-framework` and CLI command is `bpfw`.
