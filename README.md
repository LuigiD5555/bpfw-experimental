# BPFW — Blueprint Framework

BPFW verifies that a codebase still matches its declared blueprint: it catalogs code units, tracks their declared purpose and status, and blocks changes that drift from the authority. This repository holds the framework source and a portable terminal editor.

Versión en español: [README.es.md](README.es.md).

## Install

Install a tagged release straight from GitHub:

```sh
pip install "blueprint-framework[multilang] @ git+ssh://git@github.com/LuigiD5555/bpfw-experimental.git@v0.3.0"
```

Or build a wheel from a checkout and install it with the bundled installer:

```sh
scripts/fetch_pipecraft.sh                      # PipeCraft runtime from the release, checksum verified
python -m build                              # writes dist/
scripts/install.sh                           # or: BPFW_WHEEL=/path/to/wheel scripts/install.sh
```

`[multilang]` adds the tree-sitter parsers for HTML, CSS, Go and Rust.

## Quick start

```sh
bpfw editor --project-root /path/to/project
bpfw verify --project-root /path/to/project
bpfw authority doctor --project-root /path/to/project
```

Lighter storage and markup granularity (0.3.0):

```sh
bpfw authority regranulate --project-root . --profile meaningful          # preview
bpfw authority regranulate --project-root . --profile meaningful --apply  # apply
bpfw authority compact --project-root .                                   # preview; add --apply to write
bpfw history compact --project-root .                                     # preview; add --apply to write
python scripts/measure_metadata.py --project-root /path/to/project        # read-only sizes
```

Set `markup_granularity` in the project blueprint to:
- `full` (default): every HTML element and CSS rule becomes a unit.
- `meaningful`: wrapper elements are skipped. Forms, controls, sections, elements with an id and top-level CSS statements remain.

## Storage and protection

- The SQLite authority is the source of truth. The YAML snapshot is generated from it.
- Protection is a logical guard (`bpfw lock` / `bpfw unlock`), not operating-system immutability. Unlocking asks for `sudo` authentication.
- Maintenance commands preview by default. The audit trail (`operation_log`) is always kept.

## Documentation

- [CHANGELOG](docs/CHANGELOG.md): release notes.
- [docs/history/](docs/history/): delivery notes and the earlier validation record, kept for reference.

## Development

```sh
python3.13 -m venv .venv-dev
.venv-dev/bin/pip install -e '.[multilang]' 'pytest>=9,<10' 'pytest-readable>=0.2,<0.3'
.venv-dev/bin/python -m pytest -q tests/test_lightweight_metadata.py
```

Catalog hashes come from Python 3.13's `ast.dump`, so use Python 3.13 for catalog checks.

## License

MIT. See [LICENSE](LICENSE).
