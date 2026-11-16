# BPFW post4 — Implementación CLI exploratoria (19 de octubre de 2026)

## Base, arquitectura y límites

Base: ZIP suministrado `BPFW_SQLITE_INTEGRACION_CONSOLIDADA_03_2026-10-19.zip`.

La implementación conserva SQLite como autoridad y Blueprint Engine como **único escritor semántico**; no crea un segundo almacenamiento de autoridad ni un motor de decisiones. Se redujo la duplicidad de renderizadores de tablas de Editor: el Editor anterior basado en YAML fue eliminado junto con su sesión, filtros, búsqueda y motor de tablas; `integrations/editor/__init__.py` y `cli.py` enrutan exclusivamente al navegador SQLite. YAML sigue siendo un formato de **importación explícita** mediante `bpfw migrate`, sin mantener un editor o escritor YAML paralelo.

**No constituye una certificación de paridad total** para todos los flujos interactivos de Inspector, Drift, Diff y Planner. La navegación del catálogo SQLite y su edición transaccional sí están implementadas; los subsistemas de decisión conservan sus flujos existentes, pero la pantalla de Drift, el filtro de Diff y el listado de Planner aprovechan componentes compartidos. No se eliminaron controladores de dominio cuyo borrado habría roto decisiones existentes.

## Archivos y responsabilidades modificados

| Módulo | Responsabilidad | Dependencias |
|---|---|---|
| `core/authority/sqlite/queries.py` (nuevo) | `Query`, `Cursor`, `Page`, `AuthorityQueries`: compilación de filtros whitelist, páginas keyset por revisión, facetas y fichas con relaciones | `SqliteAuthorityStore.connect` en modo lectura |
| `integrations/shared/cli_explorer/presentation.py` (nuevo) | Sanitización de datos de autoridad, Unicode, tablas compactas/verticales, fichas y valores anidados | Ninguna escritura ni acceso a SQLite |
| `integrations/shared/cli_explorer/controller.py` (nuevo) | Pila de páginas, ficha, selector UID/revisión, filtros, columnas, parser contextual, preview, confirmación y exportación | `AuthorityQueries`; `BlueprintEngine` sólo para cambios |
| `core/authority/sqlite/editor.py` (reescrito) | Un solo punto de aplicación para modo interactivo y flags script; parches tipados | `BrowserController`, `BlueprintEngine` |
| `core/authority/sqlite/commands.py` | TTY interactivo automático; no TTY/JSON sin prompts; modos `auto/compact/vertical/table` | `run_editor` |
| `integrations/editor/{screen,session,search,filters}.py` | **Eliminados:** no existe un segundo Editor; todos los flujos actuales emplean SQLite | `BrowserController` y `cli_explorer.presentation` |
| `integrations/editor/__init__.py` y `cli.py` | Editor único y error explícito para proyectos que aún no han migrado desde YAML | `sqlite.commands`, `migrate` |
| `integrations/shared/terminal_io.py` (nuevo) | Entradas y tamaños de terminal reutilizables; ya no los define el Editor anterior | Planner y otras integraciones |
| `integrations/inspector/drift_gate_render.py` | Cajas de decisiones ajustadas al ancho disponible | presentación compartida |
| `integrations/diff/session.py` | Se sustituyó filtro simulado por `risk`/`kind` reales sobre el snapshot | plan/decisiones intactos |
| `integrations/planner/renderer.py` | Ajuste de nombres y conexiones al ancho de terminal; sin tocar draft | presentación compartida |
| `tests/test_cli_explorer.py` | Pruebas de consulta, paginación, renderer, edición, estado, seguridad, Diff | store de prueba real |

## Secuencias funcionales

### Abrir/consultar

`cli.main` → `sqlite.commands.run_sqlite_cli` → `editor.run_editor(interactive)` → `BrowserController.run()` → `AuthorityQueries.page()` → `SqliteAuthorityStore.connect(read-only)` → `SELECT uid,external_id,...` (sin `raw_json`) → `catalogue()` → texto seguro, con paginación. `open <n|uid>` consulta sólo el bloque y sus hijos vía `_load_blocks` en una lectura. `inspect` invoca explícitamente el Inspector existente (con su preflight) y retorna a la misma ficha y filtros, actualizando la revisión del bloque y reiniciando paginación si la autoridad cambió. `b` regresa al catálogo sin perder filtros ni selección.

### Filtrar, ordenar y seleccionar

`search/f/sort` construye una nueva instancia `Query`, valida las columnas mediante allowlist y aplica SQL parametrizado. El resultado usa `ORDER BY sort, uid` y un cursor con `fingerprint` y `authority_revision`. Si la autoridad cambia entre páginas se invalida el cursor y se vuelve a página inicial con mensaje; los UID previamente elegidos no se reasignan. `m all` obtiene un snapshot acotado (máximo 10,000 UID y revisiones) de la consulta filtrada, no de la página actual.

### Modificación masiva

`m` (o `open`) → `edit field=value`/`clear field` → parches `{uid,expected_entity_revision,field,op,value}` en memoria → `review` invoca `BlueprintEngine.preview_authority_patches` → `apply` solicita escribir literalmente `APPLY` → `BlueprintEngine.apply_authority_patches` → SQLite transaccional + operation log/outbox → invalidación de la vista. Un conflicto de revisión, bloqueo o validación aborta el commit. `q`, `b`, los cambios de filtro y `review` no escriben autoridad.

### No TTY y automatización

`bpfw editor` en salida redirigida imprime el catálogo sin leer `stdin` ni emitir secuencias ANSI; `--json` conserva JSON parseable. Los flags script preservan `--select`, `--all` limitado por `--limit`, `--set`, `--clear`, `--apply`. Los límites de seguridad para la consulta script son 10,000 filas y 100,000 celdas por transacción.

### Exportación

`export csv <ruta>` o `export json <ruta>` crea un temporal en el directorio destino, usa una transacción de lectura y emite resultados en lotes de 200 registros, con un máximo explícito de 10,000 filas. Verifica la revisión al terminar antes de publicar el archivo. En CSV, neutraliza fórmulas de hojas de cálculo. No exporta una tabla truncada.

## Comandos de interfaz

```
? | h | help             ayuda contextual
n | next, p | prev        páginas
first                     primera página
b | back, q | quit         regresar / salir
2 | open 2 | open <uid>    abrir bloque
/ texto | search texto    búsqueda literal
f field=value             filtro acumulativo
f list | f remove N | f clear
sort field [asc|desc]
group domain|status|kind   agrupar mediante facetas
cols                      perfiles disponibles
cols technical|status|revisions|responsibilities
cols set uid,domain,status
view auto|compact|vertical
m 1,3,5-8 | m uid UID | m all | m clear
selected                  revisar selección
edit field=value | clear field
review | apply            preview / confirmación explícita
relations | impact | detail intent | history | issues | inspect
export csv|json <ruta>
```

**Distinguir `m all` de `--all`:** en navegador `m all` selecciona todos los resultados del filtro actual (máximo 10,000); en script `--all` sólo opera dentro de los primeros `--limit` resultados, igual que la versión anterior.

## Verificación disponible en este entorno

- 72 pruebas y 45 subtests aprobados en suites combinadas de SQLite, Editor, seguridad y duplicados.
- 27 pruebas nuevas de navegación, filtros, paginación por clave, selección, conflictos, bloqueo, terminal estrecha, inyección de control, exportación, integración Diff y ausencia de scanner al listar.
- La batería general con todos los módulos no pudo recolectarse porque falta `pytest_readable`; los tests de parsers opcionales también requieren paquetes Tree-sitter ausentes.
- Microbenchmark local (8,000 bloques; SQLite 4,878,336 bytes): importar 0.275 s, primera página de 30 filas 1.352 ms, segunda 1.244 ms, facetas 0.766 ms, pico de asignaciones de Python observado por `tracemalloc` durante esas consultas 46.55 KiB. Estas medidas son específicas de este entorno y no sustituyen las comparaciones sobre un proyecto real de 20–50 MB ni incluyen toda la memoria del proceso.

## Límites y pendientes de paridad

1. El explorador de Editor es funcional; los controladores de decisiones complejas de Inspector, Diff, Drift y Planner no fueron reconstruidos completamente. Se evitó reescribir el sistema de decisiones a ciegas.
2. El Editor ya no contiene la antigua ruta YAML de búsqueda o edición: antes de abrirlo debe ejecutarse la migración explícita a SQLite. La migración original conserva su funcionamiento, pero no existe dual-write. Este es un cambio intencional de compatibilidad de la CLI.
3. No se ha instalado o validado la batería multilenguaje opcional ni la experiencia PTY en Windows/macOS.
4. Aún no se han medido índices/FTS ni benchmarks en la autoridad del usuario de 20–50 MB.
5. Por diseño, una selección masiva superior a 10,000 responsabilidades se rechaza; debe acotarse el filtro o usar Batch CSV.

## Recomendación de validación previa a instalación estable

Crear una copia del proyecto real. Migrarla a SQLite si es necesario, probar `bpfw editor`, filtrar, abrir dos fichas, seleccionar decenas de bloques, previsualizar, confirmar y ejecutar `bpfw verify`, `bpfw diff`, `bpfw inspector` y `bpfw history`. Validar especialmente revisiones obsoletas y cambios de estado que excluyan bloques del filtro activo.
