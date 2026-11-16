# BPFW — Explorador CLI portátil (post5)

La CLI interactiva está desacoplada de SQLite y del modelo de Blueprint mediante un contrato de adaptador. Los repositorios BPFW se abren por `--project-root` y comparten el mismo navegador sin compartir sus estados. El único Editor SQLite utiliza `BpfwExplorerAdapter` y Blueprint Engine para escribir. También hay un adaptador de catálogo independiente (`MemoryExplorerAdapter`) para demostrar reutilización.

**Arquitectura y pruebas:** [CLI_PORTABLE_ENTREGA_05.md](CLI_PORTABLE_ENTREGA_05.md). **Antecedentes de navegación:** [CLI_EXPLORATORIA_ENTREGA_04.md](CLI_EXPLORATORIA_ENTREGA_04.md).

```sh
pip install ./blueprint_framework-0.2.0a14.post5-py3-none-any.whl
bpfw editor --project-root /ruta/proyecto-a
bpfw editor --project-root /ruta/proyecto-b --search validator --json
```

Editor exige SQLite como autoridad y conserva migración explícita desde YAML. Los cambios interactivos pasan por `review` y `apply` con confirmación `APPLY`. Las versiones YAML anteriores no tienen otro Editor en paralelo.

**Estado:** refactor funcional probado con catálogos SQLite y datos no BPFW. No se certifica todavía la suite opcional completa ni la ejecución sobre los repositorios más grandes. La protección SQLite sigue siendo lógica, no una protección inmutable del sistema de archivos.

---

# Blueprint Framework — SQLite integration post4 (historical base) (CLI exploratoria)

The previous `0.2.0a14.post4` build adds the shared terminal explorer to the working post3 SQLite base. See [CLI implementation details](CLI_EXPLORATORIA_ENTREGA_04.md) and [prior post3 fixes](SQLITE_INTEGRACION_ENTREGA_03.md).

BPFW 0.2.0-alpha.14, con almacenamiento de autoridad SQLite, migración desde YAML, Blueprint Engine semántico, Editor masivo, CSV, sesiones, verificación e historial integrados en rutas principales, con limitaciones documentadas.

**Antes de instalar o migrar un proyecto importante**, lee [`SQLITE_INTEGRACION_ENTREGA_02.md`](SQLITE_INTEGRACION_ENTREGA_02.md). La integración incluye más comandos que post1, pero no está certificada para producción y la seguridad SQLite es lógica, no una protección OS inmutable.

Instalación en un entorno virtual: `pip install ./blueprint_framework-0.2.0a14.post5-py3-none-any.whl`. Para instalación de usuario, `./install.sh --without-multilang` (requiere dependencias de Python disponibles).
