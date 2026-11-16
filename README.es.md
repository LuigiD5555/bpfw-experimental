# BPFW — Blueprint Framework

BPFW verifica que un código base siga coincidiendo con su blueprint declarado: cataloga las unidades de código, registra su propósito y su estado declarados, y bloquea los cambios que se separan de la autoridad. Este repositorio contiene el código fuente del framework y un editor de terminal portable.

English version: [README.md](README.md).

## Instalación

Instala una versión etiquetada directamente desde GitHub:

```sh
pip install "blueprint-framework[multilang] @ git+ssh://git@github.com/LuigiD5555/bpfw-experimental.git@v0.3.0"
```

O construye un wheel desde un checkout e instálalo con el instalador incluido:

```sh
scripts/fetch_pipecraft.sh                      # runtime PipeCraft desde la release, con checksum verificado
python -m build                              # genera dist/
scripts/install.sh                           # o: BPFW_WHEEL=/ruta/al/wheel scripts/install.sh
```

`[multilang]` añade los parsers de tree-sitter para HTML, CSS, Go y Rust.

## Inicio rápido

```sh
bpfw editor --project-root /ruta/al/proyecto
bpfw verify --project-root /ruta/al/proyecto
bpfw authority doctor --project-root /ruta/al/proyecto
```

Almacenamiento más ligero y granularidad de marcado (0.3.0):

```sh
bpfw authority regranulate --project-root . --profile meaningful          # vista previa
bpfw authority regranulate --project-root . --profile meaningful --apply  # aplicar
bpfw authority compact --project-root .                                   # vista previa; --apply para escribir
bpfw history compact --project-root .                                     # vista previa; --apply para escribir
python scripts/measure_metadata.py --project-root /ruta/al/proyecto       # tamaños, solo lectura
```

En el blueprint del proyecto, `markup_granularity` puede ser:
- `full` (por defecto): cada elemento HTML y cada regla CSS se convierte en una unidad.
- `meaningful`: se omiten los elementos envoltorio. Se mantienen formularios, controles, secciones, elementos con id y sentencias CSS de primer nivel.

## Almacenamiento y protección

- La autoridad SQLite es la fuente de verdad. El snapshot en YAML se genera a partir de ella.
- La protección es un cerrojo lógico (`bpfw lock` / `bpfw unlock`), no una inmutabilidad del sistema operativo. Desbloquear pide autenticación con `sudo`.
- Los comandos de mantenimiento previsualizan por defecto. El registro de auditoría (`operation_log`) se conserva siempre.

## Documentación

- [CHANGELOG](docs/CHANGELOG.md): notas de versión.
- [docs/history/](docs/history/): notas de entregas y el registro de validación anterior, para referencia.

## Desarrollo

```sh
python3.13 -m venv .venv-dev
.venv-dev/bin/pip install -e '.[multilang]' 'pytest>=9,<10' 'pytest-readable>=0.2,<0.3'
.venv-dev/bin/python -m pytest -q tests/test_lightweight_metadata.py
```

Los hashes del catálogo salen de `ast.dump` de Python 3.13, así que usa Python 3.13 para las comprobaciones del catálogo.

## Licencia

MIT. Ver [LICENSE](LICENSE).
