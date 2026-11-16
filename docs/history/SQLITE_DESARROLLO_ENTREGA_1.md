# BPFW — Entrega combinada 1: SQLite + migración + edición masiva CSV

**Código real basado en `0.2.0a14` corregido (17-10-2026).** Distribución experimental `0.2.0a14.post1`, **no** lanzamiento estable ni sustitución completa de Alpha.14.

## Qué se ha implementado

- Esquema SQLite v1 con `blocks`, `artifacts`, `invariants`, `connections`, secciones de autoridad, estado/revisión, índices, `operation_log`, `operation_deltas`, `outbox_events` y procedencia de importación.
- Materialización exacta: campos raíz desconocidos, listas presentes pero vacías, `null` explícito, perfiles/defaults, orden original de los bloques, campos y hijos desconocidos; no se materializa el artefacto de `code` legacy como artefacto SQL adicional.
- Consulta paginada/filtrada, lectura por UID/ID, prefetch de hijos, detector de referencias no resueltas y `doctor` con integrity_check, FK, digest y coherencia de índices escalares. El digest se calcula en páginas de 400 bloques sin mantener el documento entero en memoria.
- Migración **explícita**, con `--plan`, staging, comparación completa, doctor y selector atómico `.bpfw/manifest.json`. Se conservan intactos los YAML originales, que dejan de ser autoridad activa.
- Cambios parciales sobre campos de bloques mediante operaciones `set` / `clear`, previsualización sin efectos, optimistic locking por revisión individual, transacción única y outbox atómico.
- `bpfw batch export` a tabla CSV y un `.baseline.json` para distinguir celdas sin cambios de borrados; importación y previsualización del CSV editado con Excel/LibreOffice. CSV de parches explícitos como alternativa.
- Puente de `BlueprintRepository` y `AutomationEngine` a SQLite. Los batches antiguos de AutomationEngine siguen materializando el documento completo como compatibilidad; no se consideran optimizados todavía.
- Editor de consulta textual `--view table` con filtros (sin edición interactiva todavía). API de cambios lógicos integrada en `core/blueprint_engine/engine.py`.
- Backup consistente SQLite y barreras explícitas contra writers YAML heredados.

## Uso seguro: PROBAR SOLO EN COPIA DEL PROYECTO

Instalar mediante `bash install-pinned.sh` (con dependencias) o crear un entorno virtual con el wheel actualizado. **No ejecutar la migración de producción todavía**: Inspector, Planner, Verify, Status, History, protección y parte de Diff/Drift no están completamente portados y varias órdenes quedan bloqueadas en el modo SQLite. Para trabajar con todas las herramientas de la versión actual, conservar el backend YAML.

```bash
# En una copia independiente, después de instalar:
bpfw migrate --to sqlite --plan --project-root ./copia
bpfw migrate --to sqlite --apply --project-root ./copia
bpfw authority info --project-root ./copia
bpfw authority doctor --project-root ./copia
bpfw editor --view table --domain payments --project-root ./copia
bpfw batch export --scope block --format csv --out ./copia/bloques.csv --project-root ./copia
# Editar ./copia/bloques.csv en una hoja de cálculo; conservar bloques.csv.baseline.json
bpfw batch import ./copia/bloques.csv --dry-run --project-root ./copia
bpfw batch import ./copia/bloques.csv --apply --project-root ./copia
bpfw authority backup --out ./copia/respaldo.sqlite --project-root ./copia
```

**Importación CSV:** el archivo tabular se acompaña del `.baseline.json` generado en la exportación. Sin ese archivo, se rechaza el import. Solo se permiten `name`, `purpose`, `domain`, `status`, `kind`; `uid`, `id` y `revision` no son editables desde la tabla. Si se deja vacía una celda que tenía un valor explícito, ese campo se *elimina* (clear). Una celda que originalmente estaba vacía y sigue vacía es un no-op. Borrar una fila del CSV **no borra un bloque**.

**CSV de parches:** alternativa precisa para campos anidados/`null`:

```csv
uid,revision,field,op,value
bp_001,3,status,set,deprecated
bp_002,2,domain,set,payments
bp_003,7,intent.summary,set,"Nueva intención"
bp_004,1,purpose,clear,
```

`value=null` indica JSON null explícito; `clear` suprime el campo. El fichero CSV debe usar UTF-8 (se admite BOM de Excel). Las operaciones son indivisibles: si una entidad no existe o una revisión es obsoleta, todo el archivo se rechaza sin cambios de autoridad ni historial.

## Lo que **NO** está terminado y no debe presentarse como tal

1. Inspector, Drift, Planner, Diff, Verify, protección de acceso, fuente de verdad en todos los consumidores, History/Why/Trace y Git por snapshots. En SQLite las órdenes CLI no auditadas quedan **bloqueadas**, para que nadie trabaje accidentalmente contra YAML obsoleto.
2. Editor interactivo con modificación de celdas, selección por lotes y diálogos de aprobación. La edición CSV sí funciona; la tabla por ahora es de lectura.
3. El outbox ya es atómico con los cambios, pero su proyector hacia `HistoryLedger` no existe. **No se debe purgar o publicar el outbox manualmente**.
4. Historial de deshacer/rehacer, dependencias incrementales de scanner/verificación, FTS, versionado con Git, locks a nivel aplicación para todos los writers internos, roles/permisos e integración real de safety policy en todos los comandos semánticos.
5. Migración de proyectos con datos legacy rechazados por el cargador original (por ejemplo identificadores duplicados que impiden carga). No existen instrumentos automáticos de reparación en SQLite para esos casos; se deben resolver en YAML antes de migrar.
6. `bpfw normalize`, `compact`, los batches existentes, `BlueprintRepository.save` pueden tener costes de materialización O(N). Los parches CSV de campos simples usan actualizaciones por registro, pero el digest auditado requiere leer la autoridad completa en streaming: tiempo O(N), memoria acotada.
7. Probar en proyectos reales de 20–50 MB, con dependencias opcionales de idiomas y estrés de concurrencia/memoria. No se promete reducción determinada de espacio ni compatibilidad de producción.

## Contratos en código

| API | Responsabilidad |
|---|---|
| `SqliteAuthorityStore.initialize()` | Crea DB y schema en ruta nueva, nunca sobrescribe DB existente |
| `.load_document()` | Compatibilidad documental exacta, materialización completa cuando la API heredada la exige |
| `.get_block()` / `.list_blocks()` | Consultas selectivas con índices, filtros y page limit |
| `.import_document()` | Primera importación, única transacción y journal/outbox |
| `.apply_patches()` | Validación de revisiones, cambio lógico, SQL incremental, outbox; preview mediante rollback |
| `.replace_document()` | Compatibilidad antigua: diff con actualización de registros afectados |
| `.doctor()` | Valida DB, relaciones e integridad semántica de proyecciones |
| `.backup()` | API nativa de backup de SQLite |
| `migration_preview()` / `migrate_legacy()` | Verificación, staging, equivalencia y activación manifiesto |
| `BlueprintEngine.preview_authority_patches()` / `.apply_authority_patches()` | Entrada semántica común de parches CSV |
| `export_blocks()` / `import_csv()` | Intercambio CSV, comparación contra baseline y control de versiones |

## Tests

```bash
PYTHONPATH=src pytest -q tests/test_sqlite_authority.py tests/test_editor_workflow.py tests/test_security_metadata.py tests/test_duplicate_groups.py
```

Durante esta entrega: **32 tests aprobados, 45 subtests aprobados** (incluyendo 14 pruebas nuevas SQLite). Nota: la suite independiente `test_html_templates.py` depende de `tree_sitter` y gramáticas opcionales no instaladas en este entorno; no se contabiliza como pasada.

## Siguiente entrega combinada recomendada

Migrar los últimos lectores y *todas* las rutas heredadas de escritura a las operaciones semánticas, integrar verificador incremental y protección, y conectar outbox a historial antes de habilitar SQLite como backend de uso diario. Añadir después Editor interactivo (no solo tabla de lectura) y benchmarks sobre proyectos grandes. Hasta entonces, trabajar con copias.

**Advertencia de CSV:** algunos programas de hojas de cálculo interpretan celdas que comienzan con `=`, `+`, `-` o `@` como fórmulas. Importa solo datos de autoridad de confianza y revisa los campos antes de abrirlos en un programa externo.
