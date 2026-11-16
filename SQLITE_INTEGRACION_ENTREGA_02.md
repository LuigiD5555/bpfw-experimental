# BPFW — Integración SQLite consolidada (post2)

**Base:** BPFW 0.2.0a14.post1, que ya contenía esquema SQLite, migrador, tabla de lectura y CSV. **Entrega:** `0.2.0a14.post2`. Fecha 2026-10-19.

## Estado implementado y probado

- `AuthorityRepository.load/save` materializa el contrato histórico desde SQLite y persiste el documento dentro de una transacción; conserva procedencia de sharding lógico y rechaza escrituras con revisiones obsoletas.
- `BlueprintRepository` comparte `AuthorityDocument` con las sesiones y Verify; lecturas de Verify/Status usan SQLite en lugar de YAML preservado.
- `BlueprintEngine.preview_changes/apply_changes` y `AuthorityPatchEngine` utilizan un intérprete de planes SQLite con los 15 tipos de operación del engine (bloques, metadatos, referencias al código, shard lógico, reglas ignore/covered) y confirman una sola transacción. No escribe shards YAML.
- `Inspector.save_blueprint`, `Planner.assembler`, `AuthoritySessionManager` conectados al repositorio; las sesiones pendientes guardan la revisión de origen y rechazan aplicaciones obsoletas.
- Las rutas de persistencia YAML protegidas mantienen barreras explícitas en modo SQLite. La salida de `HistoryLedger.read_authority_snapshot` ahora usa SQLite; los eventos en el outbox se proyectan idempotentemente al historial semántico durante las consultas.
- `Verify` incorpora hallazgos relacionales de referencias sin destino y artefactos duplicados. `authority doctor` realiza revisiones estructurales más profundas. La firma de caché incorpora revisión SQLite y no observa los YAML heredados.
- Edición por tabla TUI `editor --interactive`, selección `editor --all` o `--select`, múltiples `--set` y `--clear`, previsualización, confirmación y un único commit. CSV export/import de post1 sigue disponible.
- `authority export` emite JSON determinista y `authority restore` realiza previsualización / respaldo SQLite / reemplazo transaccional. `authority backup` usa backup API de SQLite.
- `lock/unlock` gestionan bloqueo **lógico de aplicación**; no se anuncia como equivalente a la protección inmutable del sistema operativo. Las modificaciones SQLite consultan este guard; se conserva compatibilidad con DBs post1 sin tabla de guard.
- Se admiten las órdenes `verify`, `status`, `history`, `why`, `trace`, `run`, `inspector`, `planner`, `intent`, `batch`, `normalize`, `compact`, `editor` con las rutas unificadas indicadas. `init` no puede sobrescribir autoridad migrada; re-inicializar es una operación distinta.

## Comandos principales

```bash
# Ejecutar en copia antes de migrar una autoridad de trabajo
bpfw migrate --to sqlite --plan --project-root ./copia
bpfw migrate --to sqlite --apply --project-root ./copia
bpfw authority doctor --project-root ./copia
bpfw verify --project-root ./copia
bpfw status --project-root ./copia

# Editor: previsualiza y aplica a todos los bloques filtrados
bpfw editor --domain payments --all --set status=deprecated --project-root ./copia
bpfw editor --domain payments --all --set status=deprecated --apply --project-root ./copia
bpfw editor --interactive --project-root ./copia

# Exportaciones para revisión/diff en Git y recuperación
bpfw authority export --out blueprint-snapshot.json --project-root ./copia
bpfw authority restore --input blueprint-snapshot.json --project-root ./copia
bpfw authority restore --input blueprint-snapshot.json --apply --project-root ./copia

# Protección lógica
bpfw lock --project-root ./copia
bpfw unlock --project-root ./copia

# CSV tabular y parchado
bpfw batch export --scope block --format csv --out blocks.csv --project-root ./copia
bpfw batch import blocks.csv --dry-run --project-root ./copia
bpfw batch import blocks.csv --apply --project-root ./copia
```

## Pruebas ejecutadas

`PYTHONPATH=src pytest -q tests/test_sqlite_authority.py tests/test_sqlite_full_integration.py tests/test_editor_workflow.py tests/test_security_metadata.py tests/test_duplicate_groups.py`:
**45 tests aprobados, 45 subtests aprobados.** Se incluyeron pruebas de migración, lectura/escritura por los dos repositorios, planes semánticos, procedencia, CAS, protección lógica, editor CLI, outbox, verificación relacional, exportación/restauración y ausencia de escrituras sobre YAML legado.

`PYTHONPATH=src pytest -q tests`: **48 aprobados, 12 fallaron**, todos del módulo `test_html_templates.py` por no disponer en este entorno de `tree_sitter` y gramáticas opcionales HTML/CSS/Go/Rust; los fallos se deben a `LanguageAdapterUnavailable`, no fueron corregidos ni ocultados.

## Límites que siguen requiriendo validación, no proclamar producción

1. **Inspector y Planner interactivos completos** no se ejecutaron de extremo a extremo con TTY real y proyectos grandes; se migraron sus rutas de persistencia, pero ciertas bifurcaciones del flujo de interfaz podrían necesitar adaptación adicional.
2. **Drift Manager, Diff y metadatos de sesiones antiguas** no se probaron exhaustivamente en sus edge cases de refactors, recuperación múltiple, Back y quit. No asumir paridad total sin esas pruebas.
3. **Bloqueo lógico** no impide que procesos externos o usuarios con permisos de archivo abran SQLite directamente. Se requiere política de archivos/permisos si el modelo de seguridad depende de OS immutability.
4. **Integridad y memoria:** rutas históricas de Verify/Inspector materializan el documento entero; el CSV y la tabla son selectivos. No hay benchmark validado con autoridades reales de 20–50 MB; tampoco reducción cuantificada de RAM/espacio.
5. **Git:** exportación JSON manual, pero no se ha construido un hook automático por rama/merge ni resolución bidireccional de conflictos.
6. **Historial:** outbox transaccional y proyección idempotente para consultas; eventos antiguos siguen en la estructura heredada. No hay Undo/Redo semántico completo ni compactación/retención de objetos de historial.
7. **Edición TUI:** selección múltiple y confirmación, pero no una cuadrícula de celdas editable tipo Excel ni UI gráfica.
8. **Seguridad y despliegue:** no se hicieron pruebas de fuzz, estrés multiescritor, fallos por corte eléctrico ni instalación en múltiples distribuciones. El paquete conserva las dependencias opcionales de parsers, sin incluirlas.

**Resultado:** integración consolidada y funcional de los puntos centrales, pero **no certificación de integración completa lista para producción**. Conservar backups y ejecutar en una copia del proyecto real.
