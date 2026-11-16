# 2026-10-19 — 0.2.0a14.post5: navegador CLI portable

- Único navegador sin imports SQLite, BPFW Core, Inspector ni Blueprint Engine.
- Adaptador BPFW por raíz de proyecto y adaptador de catálogo independiente.
- Registro extensible de adaptadores, filtros/columnas/fichas definidos por fuente.
- Cambios optimistas con validación por Blueprint Engine; navegación y edición desacopladas.
- Exportaciones por adaptador; salida no interactiva preservada.
- Suite disponible: 77 pruebas y 45 subpruebas aprobadas; dependencias opcionales faltantes.

# CLI exploratoria consolidada — 2026-10-19 (0.2.0a14.post4)

- Un único Editor SQLite y un renderizador adaptable: se retiró el Editor YAML, sus filtros, buscador, sesión y motor de tablas duplicados. YAML permanece importable mediante migración explícita (sin escrituras paralelas).
- Editor SQLite con SQL de proyección y paginación keyset; sin cargar documentos completos ni invocar scanner para listar.
- Búsqueda, filtros acumulables, ordenación, agrupación por facetas, columnas configurables, fichas de responsabilidad, relaciones, historial y diagnósticos explícitos.
- Ficha con entrada explícita `inspect` al Inspector actual y retorno al contexto/filtros del catálogo, sin scanner al abrir o paginar el Editor.
- Selección múltiple por UID/revisión, navegación entre páginas, vista previa y confirmación de escritura mediante Blueprint Engine; los scripts `--all`, `--set`, `--clear`, `--select`, `--apply`, `--json` permanecen disponibles.
- Exportación de resultados por CSV/JSON en streaming y con detección de cambios concurrentes. Protección ante fórmulas de hoja de cálculo en CSV y controles de terminal.
- Diff: filtros reales por `risk` y `kind`, sin modificar el estado de decisiones y planes.
- Drift Gate: cajas de operación adaptadas al ancho, sin alterar decisiones ni `Back`.
- Planner: listado de bloques y conexiones con ajuste de ancho, preservando borradores locales; sus prompts y medidas de terminal pasaron a `integrations/shared/terminal_io.py`.
- Pruebas de navegación, seguridad y regresión; véase `CLI_EXPLORATORIA_ENTREGA_04.md`.

**Límite:** la infraestructura compartida se implementó principalmente en la exploración del Editor. Inspector, Diff y Planner conservan parte de sus renderizadores de decisión, porque sustituirlos sin pruebas de sus flujos interactivos podía provocar pérdida de estado. Este corte no acredita paridad visual completa de todos los subsistemas.

---

# Local correction — 2026-10-19 (0.2.0a14.post3)

See [correction details and regression validation](SQLITE_INTEGRACION_ENTREGA_03.md). Based on post2; original release notes follow for historical context.

# Experimental SQLite integration — 2026-10-19 (0.2.0a14.post1)

This is an **opt-in development build**, not a production migration.
The SQLite migration, logical atomic patch API, CSV import/export, database
integrity checks, and partial backend adapters are implemented.
Inspector, Planner, Verify, Status, History and other unported features are
blocked for SQLite projects rather than continuing against stale YAML.
See `SQLITE_DESARROLLO_ENTREGA_1.md` for tested features and limitations.

---

# BPFW 0.2.0-alpha.14 — Blueprint Automation

## Local corrections — 2026-10-17

This directory now contains the corrected sources under `src/bpfw`, regression tests,
and a rebuilt wheel. This is a locally corrected distribution, not a new upstream release.

- Fix variable shadowing when purpose and calculated duplicate groups coexist.
- Recognize Django template tokens and comments during HTML parsing, retaining source
  positions, original extraction text, and genuine HTML syntax findings.
- Distinguish descriptive authentication metadata from embedded credential literals.
- Accept portable root-relative HTTP defaults while retaining filesystem metadata checks.
- Allow Editor to repair declaration drift while retaining security, parser, invalid
  authority, Inspector, Planner, and verification gates.
- Invalidate reports cached before these analyzer corrections.
- Restrict Tree-sitter to the compatible 0.25 series for fresh installations.

Rebuild from this directory with `python3 scripts/build_release.py` after installing
the build prerequisites (`setuptools>=77` and `wheel`). The script rebuilds the wheel
and updates `SHA256SUMS`. Run regression tests with
`PYTHONPATH=src python3 -m unittest discover -s tests -v` in an environment with the
package's `multilang` dependencies installed. Install with `bash install-pinned.sh`.

Existing blueprint declaration drift is still reported by `bpfw verify`.

Alpha.14 keeps the alpha.13 Source Intelligence + Intent & Change Ledger and adds a deterministic automation layer intended to reduce LLM context and repetitive YAML edits.

## Added

- Root `defaults` and reusable artifact `profiles`.
- Runtime-only inheritance: effective metadata is visible to Inspector/verify without expanding compact authority YAML on save.
- `bpfw batch audit` with compact JSON summaries and opt-in `--details`.
- `bpfw batch discover-artifacts --unbound`.
- `bpfw batch generate-uids`.
- Generic batch `set`, `default`, `remove`, `rename-field`, `replace-value`, and `move-path`.
- Plan/apply transactions with authority digest / stale-plan protection.
- `bpfw normalize` for deterministic cleanup and safe metadata inference.
- `bpfw compact` for exact repeated artifact metadata -> reusable profiles.
- Profile-aware verification and `UNKNOWN_ARTIFACT_PROFILE`.
- Low-token BPFW parent/child skills and shell wrappers under `integration-assets/`.

## Preserved from alpha.13

- Python and Go source windows, location drift, parser-neutral artifacts.
- Prompts, config, specs, skills, schemas and multi-artifact `src N` inspection.
- Intent & Change Ledger (`history`, `why`, `trace`).
- Editor `[a] show all` capped at 100 rows/page with `n/p/first/last`.

## Regression status

Historical suite: **333 passed, 1 skipped, 1 inherited failure**. The remaining failure expects the old Editor search-first UX; alpha.12+ intentionally uses list-first navigation. The source-window/automation/history work introduced no additional historical regressions.

Final wheel validation: **220 RECORD entries checked, 0 mismatches**.
