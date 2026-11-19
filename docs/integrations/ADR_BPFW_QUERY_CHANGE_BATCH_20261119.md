# ADR-BPFW-QUERY-CHANGE-20261119 — Cómo llegamos al contrato de consultas precisas y cambios batch

**Plan canónico:** [BPFW-READ-API-20261119](READ_API_FOR_AGENTS_V1.md) (apartados 4, 4A, 7, 8, 9 y 11). Este ADR es **historial de decisiones y evidencia**, no un segundo plan o backlog.
**Fecha del registro:** 2026-11-19.
**Repositorio propietario:** `LuigiD5555/bpfw-experimental`.
**PR propietaria:** [#7 — API de consultas, creación, edición y batch](https://github.com/LuigiD5555/bpfw-experimental/pull/7).
**Rama:** `docs/bpfw-read-api-integration-20261119`; **destino:** `main`.
**Base observada de código:** `a4a0b374f71a2e9398e7f78c0569e0633108718f` (2026-11-16).
**Estado:** `DESIGN_DOCUMENTED / OWNER_REQUESTED_DOCUMENTATION / NOT_IMPLEMENTED / NOT_RUN / NOT_APPROVED_FOR_EXECUTION`.
**Responsabilidad:** BPFW experimental es el productor y escritor de su propia autoridad. Dendryte y Me son consumidores opcionales, no escritores alternativos.

> **Alcance de la aceptación:** la persona propietaria solicitó incorporar el refinamiento al plan y conservar el razonamiento. Esa petición autoriza **documentación** de estas decisiones, pero no elimina las comprobaciones Q0+W0, no convierte contratos candidatos en API publicada y no autoriza ejecución, CI, migraciones, desbloqueos o merge.

## 1. Problema y resultado que se busca

BPFW conserva declaraciones sobre bloques de código, intención, responsabilidad, relaciones y evidencia. Los agentes externos necesitan acceder a esos datos de forma localizada y verificable y, en una segunda etapa, proponer creaciones o correcciones sin editar manualmente centenares de declaraciones. El usuario pidió explícitamente decidir **cuándo trabajar con precisión y cuándo usar batch**; el riesgo era tener dos caminos de mutación con reglas divergentes o aceptar filtros ambiguos como órdenes de escritura.

**Resultado deseado:** consulta focal sin efectos, selección no ambigua, previsualización de cambios, aprobación independiente del host y aplicación atómica por unidad certificada; un cambio individual es un batch de tamaño 1. La información declarada se distingue de pruebas del código y de inferencias del LLM.

**Invariantes:** single writer BPFW; misma semántica en biblioteca/CLI y futuros transportes; ninguna consulta cambia authority, historia, locks, archivos o configuración; no hay escritura desde prompts; un batch no incorpora targets descubiertos después de preview; un resultado desconocido o ambiguo no se transforma en certeza.

## 2. Cronología comprobable de las decisiones

| Fecha UTC | Registro | Qué se añadió o se descubrió | Calidad de evidencia |
| --- | --- | --- | --- |
| 2026-11-16 17:44 | [`main a4a0b374`](https://github.com/LuigiD5555/bpfw-experimental/commit/a4a0b374f71a2e9398e7f78c0569e0633108718f) | Base de código experimental declarada en 0.3.0 sobre la cual se inspeccionaron los motores | **VERIFIED:** commit remoto / código consultado |
| 2026-11-19 18:04 | [`c278c26f`](https://github.com/LuigiD5555/bpfw-experimental/commit/c278c26f09a2c45934c5b802555a555ae07b1e6d) | Nace el plan de lectura para agentes sin efectos: `bpfw.query/1` | **VERIFIED:** commit de la PR |
| 2026-11-19 18:17 | [`8838e488`](https://github.com/LuigiD5555/bpfw-experimental/commit/8838e48884f947af2ade216867f646f00125f111) | Se amplía el **mismo** plan con create/patch/batch, `bpfw.change/1`, gates de autorización e idempotencia | **VERIFIED:** commit de la PR |
| 2026-11-19 18:29 | [`e3eba375`](https://github.com/LuigiD5555/bpfw-experimental/commit/e3eba3759cb0b623640ab6f8a730705ff3e73ddf) | Se documentan los contratos de precisión, selección congelada, preview, apply, atomicidad y fallos en la sección 11 | **VERIFIED:** commit de la PR |
| 2026-11-19 18:30 | [`c118ac78`](https://github.com/LuigiD5555/bpfw-experimental/commit/c118ac78967e076dca1daf1ef26327a295a73c84) | Corrección del formato del refinamiento, sin cambios de producto | **VERIFIED:** commit de la PR |
| 2026-11-19, conversación de diseño | Solicitudes expresas de la persona propietaria | Se pidió cerrar contratos, diseñar consultas y distinguir operaciones precisas de masivas; luego registrar la explicación y el razonamiento en Git | **USER_DIRECTION:** intención documentada por la petición, no prueba técnica |
| 2026-11-19, inspección de código | Rutas del repositorio listadas en §3 | Se observaron funciones existentes y diferencias de garantías entre búsqueda, preview y escritura | **CODE_INSPECTED / NOT_TESTED:** observaciones de código, no ejecución |
| 2026-11-19, registro de este ADR | Este archivo y sección 12 del plan | Las opciones, sus descartes, límites y siguiente gate quedan disponibles fuera de la conversación | **DOCUMENTED:** publicación, no implementación |

No se atribuye a esta cronología ninguna ejecución de Dendryte, test PASS, revisión de seguridad completa ni aprobación de merge.

## 3. Qué código real inclinó el diseño

Las rutas siguientes se observaron en `main a4a0b374`; deben revalidarse si `main` cambia.

| Fuente | Observación | Consecuencia de diseño | Estado |
| --- | --- | --- | --- |
| [`sqlite/queries.py`](../../src/bpfw/core/authority/sqlite/queries.py) | `AuthorityQueries.page/get/relations/resolve/matching`; páginas hasta 100; selección hasta 10 000; cursor con revision y fingerprint | Adaptar un lector paginado; no construir un editor/listador SQL alternativo. Añadir resolución precisa por `code.path/symbol/kind` y desambiguación | **CODE_INSPECTED** |
| [`sqlite/store.py`](../../src/bpfw/core/authority/sqlite/store.py) | `connect(write=False)` usa modo `ro`; `apply_patches` usa transacción, revisiones, log y outbox | Separar consultas sin efectos del escritor y aprovechar revisiones/digests | **CODE_INSPECTED** |
| [`sqlite/store.py`](../../src/bpfw/core/authority/sqlite/store.py), `apply_patches(...dry_run=True)` | `BEGIN IMMEDIATE` en vista previa, luego excepción para rollback | **No llamar «read-only puro» a esta simulación**; confirmar ausencia de efectos colaterales o diseñar un preview en memoria | **CODE_INSPECTED, comportamiento ambiental NOT_TESTED** |
| [`blueprint_engine/engine.py`](../../src/bpfw/core/blueprint_engine/engine.py) | Métodos de `preview_changes`, `apply_changes`, `preview_authority_patches`, `apply_authority_patches` y puente SQLite/YAML | Reutilizar motores con adaptadores; no prometer paridad entre backends hasta probarla | **CODE_INSPECTED** |
| [`authority/patch/engine.py`](../../src/bpfw/core/authority/patch/engine.py) | Existe `AuthorityPatchEngine`, con previsualización, backups y rollback de archivos | Probar fallo/crash multishard antes de ofrecer «all-or-nothing» en YAML | **CODE_INSPECTED** |
| [`automation/engine.py`](../../src/bpfw/core/automation/engine.py) | `create_plan` guarda JSON en `.bpfw/plans` y `apply_plan` valida digest | Preparación **persistente** explícita separada de `change.preview`, sin escritura oculta en API de lectura | **CODE_INSPECTED** |
| [`sqlite/batch.py`](../../src/bpfw/core/authority/sqlite/batch.py) | CSV utiliza UID, baseline y revisión para operaciones masivas | Conservar CSV como otro adaptador de solicitudes normalizadas, no una segunda autoridad | **CODE_INSPECTED** |
| [`authority/patch/transaction.py`](../../src/bpfw/core/authority/patch/transaction.py) | `PatchWriteContext.is_valid()` sólo exige `tool_name` no vacío | No interpretar ese contexto interno como autorización externa de un agente; introducir permiso del host ligado a hash, scope y vencimiento | **CODE_INSPECTED, riesgo de diseño, no exploit demostrado** |
| [`catalog/access_control.py`](../../src/bpfw/core/catalog/access_control.py) | Existen contextos de escritura y desbloqueo temporal | No permitir que un LLM active por sí mismo bypass de lock | **CODE_INSPECTED** |

**Incertidumbres declaradas:** no se ejecutaron pruebas de WAL, crash, concurrencia, fallos de YAML, SQL malicioso, permisos ni regresiones completas durante este refinamiento. No derivar `PASS` de leer funciones o de que exista un test.

## 4. Decisiones de arquitectura y alternativas

Las decisiones D1–D5 se **incorporan al contrato de diseño** por solicitud expresa del propietario; su estado técnico sigue siendo `CANDIDATE_UNTIL_Q0_W0` y ninguna es licencia para liberar la API.

### D1 — Una fachada de aplicación; dos superficies

- **Elegida para el diseño:** una capa de aplicación Python con `query` de lectura y `change` de preview/apply. SQLite y YAML adaptan sus capacidades; biblioteca y CLI JSON primero.
- **Alternativa A:** dejar al consumidor leer SQLite/YAML directamente. **Descartada**: acoplamiento al esquema, riesgo de inconsistencias y bypass de políticas.
- **Alternativa B:** construir MCP o REST antes del contrato. **Aplazada**: duplica superficie de seguridad y no ofrece valor probado para la primera entrega.
- **Consecuencia:** un solo writer, pruebas de paridad y errores `UNSUPPORTED_CAPABILITY` en lugar de comportamientos diferentes por transporte.
- **Reversión:** si un consumidor real exige otro transporte, añadirlo sobre la fachada, no exponer tablas.

### D2 — Precisión verificable para identificar un bloque

- **Elegida:** `EXACT_UID` y resolución estricta por identidad o por `code.path+symbol+kind` con cardinalidad 1; listado paginado, contexto/historia y diagnósticos materializados como operaciones distintas.
- **Alternativa:** resolver «el bloque más parecido» por ranking o texto libre y escribirlo. **Descartada para mutación**: puede seleccionar otra responsabilidad.
- **Consecuencia:** cero resultados devuelve `NOT_FOUND`; múltiples resultados `AMBIGUOUS_BLOCK`. La búsqueda flexible se usa para explorar, **nunca** para decidir el target final.
- **Reversión:** se podrán añadir rankings en la interfaz de exploración, pero resolverán a UID explícitos antes de preview.
- **Detalle de compatibilidad:** `bpfw.query/1` del plan inicial nombra el contrato lógico; el envelope versionado candidato usa `"schema":"bpfw.query/v1"`. No existen dos servicios distintos.

### D3 — Batch mediante selección congelada

- **Elegida:** una operación sobre `EXACT_UID`, `EXPLICIT_UIDS`, `FROZEN_FILTER` o `DERIVED_SET` resuelve identidades y revisiones en un `SelectionSnapshot` antes de preview/apply.
- **Alternativa:** volver a ejecutar en apply el filtro «todos los del dominio X». **Descartada**: podría capturar bloques nuevos o alterados entre la vista previa y la escritura.
- **Consecuencia:** plan contiene `target_set_digest`, conteo, revisiones, filtros y estado de autoridad; revalidar CAS por destino. Desfase ⇒ conflicto, nunca expansión automática.
- **Reversión:** sólo un futuro modo expresamente autorizado, con preview/revisión renovados, podría elegir targets en tiempo de apply; no está incluido en v1.

### D4 — Plan, aprobación y escritura son actos diferentes

- **Elegida:** `change.preview` sin efectos sobre authority ni persistencia automática; `batch.prepare` almacena el plan sólo si el host lo pide; `change.apply` exige autorización externa vinculada a actor, proyecto, operaciones, plan hash, alcance y expiración.
- **Alternativa:** confiar en `human_confirmed=true`, un `tool_name` cualquiera o permisos extraídos del prompt. **Descartada**: los argumentos controlados por el solicitante no constituyen aprobación confiable.
- **Consecuencia:** el permiso se revalida justo antes del commit, junto con lock, CAS, condiciones, límites y alcance. `change.status` reconcilia incertidumbre tras timeout.
- **Reversión:** nuevas clases de aprobación podrían incorporarse en el host sin cambiar el significado de `preview`.
- **Compatibilidad de nombre:** `bpfw.change/1` es el contrato lógico previo; el envelope candidato usa `"schema":"bpfw.change/v1"`.

### D5 — Atomicidad por lote certificado, no «best effort» implícito

- **Elegida:** operación individual = lote de 1; batch normal = `ALL_OR_NOTHING`. SQLite usa transacciones verificadas de autoridad, revisión, outbox y recibo de idempotencia. YAML multishard bloquea batch hasta superar pruebas de crash/rollback.
- **Alternativa:** aplicar 279 cambios válidos de 300 y reportar progreso como éxito. **Descartada**: deja authority en estado no esperado.
- **Consecuencia:** lotes demasiado grandes devuelven `BATCH_LIMIT` y propuesta de partición; cada segmento es su **propia** transacción, nunca se promete atomicidad de todos los segmentos.
- **Reversión:** un futuro modo parcial debe ser contrato nuevo y explícito, con semántica de compensación y recibos por unidad, no un flag escondido.

## 5. Contrato funcional resultante (qué debe quedar fijado)

La fuente normativa propuesta está en la [sección 11 del plan](READ_API_FOR_AGENTS_V1.md#11-diseño-de-contratos-para-implementación--refinamiento-v11-proposed-no-aprobado). La siguiente tabla conserva las fronteras de sus operaciones:

| Acción | Selección y control | Efectos | Resultado mínimo |
| --- | --- | --- | --- |
| `query.blocks.get` | UID y revisión si procede | Ninguno | Identidad, intención declarada, procedencia, rev/digest |
| `query.blocks.resolve` | Exact ID o path+symbol+kind | Ninguno | Único UID o error explícito |
| `query.blocks.list` | filtros y cursor ligados a revisión | Ninguno | Página acotada y `next_cursor` |
| `query.relations/intent/diagnostics` | límites + provenance/stale | Ninguno | Datos declarados/materializados o UNKNOWN |
| `query.selection` | regla o UID explícitos | Ninguno | Selección verificable + cardinalidad |
| `change.preview` | selección congelada + revisiones | Ninguna mutación de authority/history/locks | diff, conteos, plan digest, riesgos, conflictos |
| `batch.prepare` | plan de cambios y autorización de preparar | **Sí**: artefacto de plan auxiliar controlado | plan_id, digest, caducidad, refs |
| `change.apply` | grant host + CAS + lock + plan hash + clave de idempotencia | Sí: transacción autorizada | recibo y readback; nunca PASS de código |
| `change.status` | actor/proyecto/ID autorizado | Lectura de estado existente | resultado confirmado o UNCERTAIN |

**Reglas de campos:** `set` distinto de `clear`; `set:null` conserva la clave con valor nulo; `set_if_absent` sólo actúa cuando no existe; `replace_if_equals` compara antes de cambiar. `uid` no es editable. Prohibidos los borrados y desbloqueos automáticos por LLM. Las capacidades estructurales de artifacts/invariants/connections necesitan Q0+W0 por backend antes de activarse.

**Hipótesis de límites, NO PROMESA:** página por defecto 50, máximo 100; profundidad de relaciones 1–2; selección hasta 10 000 identidades para preview; primer apply hasta 1 000 mutaciones y 2 MiB de plan, caducidad propuesta 15 minutos. Revisar tras benchmark y pruebas de memoria/concurrencia; la respuesta no puede truncar silenciosamente su conjunto de escritura.

## 6. Peligros, negativas y criterios que deben demostrar los tests

- **Read-only real:** transacciones de lectura SQLite/WAL y YAML no alteran authority, journals, locks, cache, Git ni directorios; un `dry_run` que abre conexión writable no pasa como consulta pura.
- **Cardinalidad:** 0 candidatos, 2 candidatos y UID exacto producen respectivamente NOT_FOUND, AMBIGUOUS y un único target.
- **Concurrencia:** cambio de revisión a mitad de paginación ⇒ STALE, nunca páginas mezcladas; filtro batch revalidado jamás incluye un bloque 101 aparecido después de congelar 100.
- **Integridad:** fallo en operación N de N deja 0 cambios; ausencia de grant/lock impide todos los cambios; `set:null` se diferencia de clear.
- **Idempotencia:** reintento misma clave+plan no duplica bloque, log ni outbox; misma clave y distinto plan ⇒ conflicto; timeout tras commit ⇒ status/readback antes de repetir.
- **YAML:** fallo entre shards demuestra reversión y recuperación o batch queda deshabilitado; no declarar capacidad sólo porque exista backup.
- **Límites:** traversal, symlink escape, SQL injection, datos confidenciales, ciclos de relaciones, 10 001 destinos y planes expirados se rechazan sin escribir.
- **Compatibilidad:** CLI, biblioteca y eventual MCP usan el mismo servicio; Core público informa UNSUPPORTED cuando no sostiene la funcionalidad.

**Nota:** son oráculos de aceptación, no pruebas que hayan pasado. No hay resultados de ejecución en esta intervención.

## 7. Continuidad usando la metodología de Dendryte, sin fingir instalación

Se consultó en `LuigiD5555/dendryte` el recurso [`skills/portable-continuity/SKILL.md`](https://github.com/LuigiD5555/dendryte/blob/d3760be2702fb275a63ca1575f5fb62a94700d20/skills/portable-continuity/SKILL.md). Sus reglas útiles para este frente son: reutilizar plan y PR existentes, una sola unidad activa, conservar fuentes con SHA, hechos frente a hipótesis, un solo `NEXT_ACTION` y recibo de cambios en GitHub.

**Capacidad observada:** en el árbol de `bpfw-experimental:main` no aparece `.dendryte/project.json` ni una instalación local de la skill; tampoco se ha comprobado ejecutable o MCP Dendryte habilitado. **Resultado:** `DENDRYTE_RUNTIME_NOT_VERIFIED / ADOPTION_REQUIRED`. Se aplicó la **metodología documental** sobre la PR propietaria; **no** se instaló Dendryte, no se crearon índices ni una autoridad de control, y no se afirmó ejecución de su CLI/MCP.

**Ficha mínima de continuidad para esta unidad:**

| Campo | Registro |
| --- | --- |
| `PROJECT` | `LuigiD5555/bpfw-experimental` |
| `PLAN_ORIGIN` | `BPFW-READ-API-20261119`, documento canónico enlazado |
| `UNIT_ID` | `Q0+W0` — auditar consultas, create/patch/batch y garantías de backends |
| `SOURCE_REF_SHA` | main `a4a0b374f71a2e9398e7f78c0569e0633108718f`; revalidar al retomar |
| `AS_IS` | Hay consultas, motores, preview y patch; falta certificar efectos, permisos y compatibilidad |
| `TO_BE` | Matriz operación → implementación → backend → efecto → prueba → garantía real |
| `OWNER_CLAIM` | PR #7 dueña del **diseño**; no se adjudican archivos de implementación a otro agente |
| `FILES_SYMBOLS_ALLOWED` | Documentación de PR #7; para Q0+W0 examinar código read-only y generar evidencia focal |
| `NO_TOCAR` | `main`, código, autoridad, locks, migraciones, CI pagado, Dendryte/Me, merges |
| `FOCAL_TEST` | Diferenciar consulta pura de preview que abre `BEGIN IMMEDIATE`; medir antes/después |
| `ACCEPTANCE` | Matriz de garantías comprobadas por backend y huecos explicitados; sin afirmar PASS no ejecutados |
| `ROLLBACK` | Revisar/revertir sólo commits documentales en PR si el propietario cambia decisión; sin force-push |
| `BLOCKERS` | Verificar gates reales con ensayos y dueño antes de autorizar implementación |
| `NEXT_ACTION` | **Ejecutar Q0+W0 en entorno aislado con evidencia focal y sin modificar authority real** |

## 8. Registro de distinciones y futuras revisiones

- **DOCUMENTED / design adopted for specification:** arquitectura D1–D5 integrada por instrucción de documentar; no implica releases.
- **CODE_INSPECTED:** funciones y módulos citados localizados a la base indicada, sin afirmar pruebas.
- **PROPOSED:** schemas, DTOs, grants, límites, idempotencia persistida, batch certificados y adopción por agentes.
- **PENDING:** Q0+W0, schema JSON normativo, revisión de capacidades por backend, pruebas focales, decisiones finales de permisos, revisión del propietario para implementar.
- **NOT_RUN:** tests, benchmarks, migración, CI y ejecución Dendryte.
- **NOT_MERGED:** la PR #7 es Draft; conservar su rama hasta revisión y aceptación, sin inventar cierre.

**Única próxima acción:** completar la auditoría Q0+W0, guardando evidencia de consultas puras, transacciones, CAS, idempotencia y YAML multishard, antes de declarar listo el contrato para implementación.
