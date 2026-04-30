# Blueprint Framework (BPFW)

Blueprint Framework (BPFW) is an MVP catalog control tool for Python projects.

This repository contains only the framework code (no application/domain code from the original project).

## What it provides

- `bpfw/blueprint.yaml` catalog generation
- Catalog validation against discovered Python code
- Drift detection for declared responsibilities
- MVP blueprint lock/unlock state
- Human-readable `verify` and `status` reports

## Install (editable)

```bash
pip install -e .
```

## CLI

```bash
bpfw init
bpfw wizard
bpfw verify
bpfw status
bpfw lock
bpfw unlock
```

## Project root resolution

When running BPFW against another project, point it to that project root:

```bash
bpfw verify --project-root /path/to/target-project
```

The target project may contain `bpfw/blueprint.yaml`. If it does not, run `bpfw init`.

## Lock State

`bpfw lock` and `bpfw unlock` manage the MVP protection state for:

```text
bpfw/blueprint.yaml
```

## Notes

- Internal Python package path is `bpfw`.
- Distribution/package name is `blueprint-framework` and CLI command is `bpfw`.
