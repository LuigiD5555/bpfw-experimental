# BPFW — Contratos de consultas y cambios controlados para agentes (propuesta V1)

**ID:** BPFW-READ-API-20261119
**Estado:** PROPOSED / NOT_IMPLEMENTED / NOT_APPROVED
**Fecha:** 2026-11-19
**Propietario del contrato:** Blueprint Framework; esta especificación NO autoriza implementar, migrar SQLite, cambiar authority, publicar endpoints, CI de pago o hacer merge.
**Alcance:** dos superficies separadas: bpfw.query/1 para lectura pura y bpfw.change/1 para preview y apply autorizados. Biblioteca Python y CLI JSON primero; MCP/HTTP, sólo si se comprueba necesidad y seguridad. Ambas son PROPUESTAS, no endpoints existentes.
**Base inspeccionada:** bpfw-experimental main a4a0b374f71a2e9398e7f78c0569e0633108718f. Revalidar HEAD antes de implementar.

## 1. Problema, objetivo y valor

BPFW mantiene datos sobre unidades de código, su propósito declarado, ubicación, dominio, historial y protección de autoridad. Los agentes externos necesitan consultarlos de forma selectiva, estable, acotada y segura, sin acoplarse a tablas internas SQLite/YAML ni disparar escrituras. Dendryte puede reunirlos con datos Git y planes; un LLM puede formular mejores hipótesis y estrategias, sin que BPFW ni Dendryte ejecuten modelos.

**Promesa medible:** ante un identificador de trabajo y un conjunto de rutas/símbolos, un consumidor recibe bloques, propósitos, relaciones, cambios conocidos, advertencias y procedencia en JSON, mediante lecturas sin efectos y con límites explícitos. Sin BPFW o sin una capacidad, el cliente degrada con honestidad, sin inventar información.

**No objetivos:** convertir BPFW en orquestador, escribir código fuente por petición de authority, exportar SQLite sin controles, duplicar el journal de Dendryte, crear un daemon obligatorio ni servir HTTP en la primera entrega. No dar autoridad de escritura a prompts ni a SCEP.

## 2. Estado actual comprobado y límites

**VERIFIED (fuentes GitHub, no tests en esta intervención):**
- El paquete público blueprint-framework expone Core centrado en init, verify, status, lock, unlock, watch y reshard; su README no promete una API de intención equivalente a experimental.
- bpfw-experimental declara versión 0.3.0 e incluye CLI history, why, trace, intent, batch, authority y consultas JSON en varios comandos.
- src/bpfw/core/history/commands.py contiene trace_location, búsqueda del bloque por ruta/línea y consulta de HistoryLedger.
- src/bpfw/cli.py tiene rutas de consulta del historial, pero el camino verify puede invocar capture_artifact_state; status puede seguir rutas de sincronización de shards. Estos comandos no son un contrato puro de lectura.
- Experimental declara SQLite como authority activa y YAML como snapshot generado; la base pública tiene otra superficie. No asumir equivalencia ni paridad de despliegue.
- Los documentos históricos describen un almacenamiento SQLite, revisiones y operaciones selectivas; su existencia no acredita que todas las rutas del CLI sean aptas para exportación segura.
- **Escrituras existentes, comprobadas en código fuente (NO probadas aquí):** BlueprintEngine.preview_changes/apply_changes, preview_authority_patches/apply_authority_patches; AuthorityPatchEngine contempla CREATE_BLOCK y UPDATE_BLOCK_METADATA; AutomationEngine permite batch set/default/remove/rename-field/replace-value/move-path y plan/apply; SQLite contiene apply_patches/replace_document, revisiones, operation_log y outbox. **No está comprobado que todas las operaciones sean paritarias ni seguras en ambas autoridades.**

**PENDING / REQUIRED:** auditar efectos e imports de consultas y escrituras; mapear capacidades reales de creación, modificación y batch por backend; revisar locks, idempotencia, revisiones, atomicidad, permisos, bitácoras, límites y recuperación de errores. No clasificar ninguna operación como READ_ONLY_VERIFIED sin test de no mutación.

## 3. Decisión arquitectónica recomendada

Alternativa A (**preferida**): una fachada de aplicación en BPFW con contratos independientes de consulta y cambios, ambos apoyados en el backend activo y DTOs versionados; CLI JSON como primer transporte, sin servidor. Cambio = preview primero, apply posterior con autorización externa. Consumidores externos llaman un ejecutable autorizado por ruta y argumentos predefinidos.

Alternativa B: MCP de BPFW para lectura y, si se aprueba específicamente, para acciones con efecto separadas y permiso por llamada. Añadirlo después de verificar los contratos y disponer de un consumidor; no duplicar la lógica Python.

Alternativa C: REST HTTP local. No incorporarlo inicialmente: sockets, orígenes, autenticación, exposición, concurrencia y nuevos riesgos no se justifican con un consumidor Rust que puede leer la salida JSON de una CLI.

Las tres alternativas pueden usar **la misma capa de aplicación Python**, con puertas separadas de consulta y mutación. Ningún transporte debe acceder directamente a las tablas SQLite ni redefinir semánticas de authority.

## 4. Contrato candidato bpfw.query/1 (NUEVO; no implementado)

Propuesta de superficie lógica; nombres de comandos finales sujetos a auditoría:
- capabilities: variante, versión, backend, operaciones disponibles y garantías de lectura.
- snapshot: revisión/digest de authority, tipo de backend, fuente y cobertura de lectura.
- blocks.list: paginación determinista por uid/id y filtros path, domain, kind, status.
- blocks.get: identificador estable, propósito declarado, origen, localización y metadata permitida.
- blocks.trace: ruta y posición → bloques/artefactos conocidos; UNKNOWN si resolución incompleta.
- intent.why: eventos y motivos explícitos asociados a bloque o cambio.
- relations.list: relaciones/invariantes declaradas; no inferir dependencias tácitas.
- diagnostics.list: leer diagnósticos ya materializados y versionados, **sin ejecutar verify ni status**.

Ningún método de consulta aplica parches, libera bloqueos, ejecuta código del proyecto, sincroniza shards o registra automáticamente nuevos eventos. La familia apply/accept/migrate queda fuera del contrato.

### Envelope de solicitud y respuesta

Ejemplo conceptual, no API real:

    request:
      schema: bpfw.query/1
      operation: blocks.list
      project_root: /ruta/autorizada
      filters: {path: src/pkg/module.py}
      limit: 40
      cursor: null
      max_bytes: 65536
    response:
      schema: bpfw.query/1
      status: COMPLETE
      authority: {backend: sqlite, revision: "...", digest: "..."}
      data: {blocks: [...]}
      provenance: {source_kind: BPFW_AUTHORITY, scope: "blocks"}
      warnings: []
      next_cursor: null

Los objetos y claves finales deben diseñarse junto a pruebas de serialización y consumidores; no publicar este ejemplo como schema aceptado.

### Invariantes de salida

1. **Identidad:** uid si existe; id visible, code.path, symbol y kind; no fusionar bloques por similitud. UID ausente ⇒ UNKNOWN/AMBIGUOUS.
2. **Procedencia:** version de BPFW, backend, revision/digest de authority, origen de campo, timestamp de observación como metadata, y referencia a código cuando el host la provee. No declarar que SQLite local está en Git.
3. **Consistencia:** una consulta paginada se vincula a una revisión/digest y rechaza cursors obsoletos; no mezclar snapshots al pasar páginas.
4. **Privacidad:** redacción explícita, allowlist de raíces y propiedades, sin secretos, RAW sensible ni rutas fuera del proyecto.
5. **Semántica:** DECLARED no equivale a VERIFIED; UNKNOWN no equivale a vacío; un informe de drift no equivale a prueba de regresión.
6. **Límites:** bytes, filas, tiempo y profundidad por petición; orden estable, errores tipados, sin resultados truncados silenciosamente.
7. **Sin efectos:** no modificar authority SQLite/YAML, archivos de historial/cache, locks, metadatos de proyecto ni git status; sin disparar scans/verificaciones de escritura.
8. **Interoperabilidad:** si el consumidor solo necesita un bloque, no volcar todo el blueprint. Schema/version y campos opcionales permiten compatibilidad.
9. **Garantía:** el host sólo puede presentar READ_ONLY_VERIFIED para una operación después de ejecutar su prueba focal; readback de salida no equivale a garantía de seguridad de toda la instalación.

### Errores mínimos

UNSUPPORTED_CAPABILITY, PROJECT_FORBIDDEN, AUTHORITY_MISSING, AUTHORITY_UNAVAILABLE, STALE_SNAPSHOT, CURSOR_INVALID, AMBIGUOUS_BLOCK, REDACTED, BUDGET_EXCEEDED, INVALID_REQUEST, QUERY_FAILED. Errores propios del CLI pueden mapearse sin crear un catálogo paralelo si el consumidor lo permite.


## 4A. Contrato candidato bpfw.change/1 — crear, actualizar y operar en batch (NO IMPLEMENTADO)

**Propósito:** permitir a agentes y herramientas preparar nuevas declaraciones de autoridad BPFW, modificar campos y componer varios cambios en un lote, sin obligar al usuario a editar manualmente cada bloque. El endpoint NO crea archivos de código fuente ni toma decisiones de arquitectura: se limita a la autoridad BPFW y reutiliza sus motores actuales. Un LLM puede PROPONER; sólo el host autorizado puede APLICAR.

### 4A.1. Operaciones lógicas candidatas

| Operación | Finalidad | Garantía |
| --- | --- | --- |
| change.capabilities | Descubrir opciones reales por backend y versión | UNSUPPORTED explícito donde no exista |
| change.preview | Generar un plan tipado con diff, conflictos, revisiones y efectos esperados | Sin mutación de authority ni journal |
| change.apply | Aplicar plan específico con autorización externa y revisión vigente | Un único writer BPFW con readback |
| change.status | Reconciliar operación por ID tras timeout o caída | No reintentar escritura a ciegas |
| blocks.create | Crear una declaración de bloque con identidad/propósito | Detectar colisiones y validar autoridad |
| blocks.patch | Cambiar campos permitidos: set, clear, set_if_absent | UID estable y revisión esperada |
| artifacts.create/patch | Declarar o corregir artefactos asociados | Backend compatible y validación de rutas |
| invariants.create/patch | Proponer invariantes y actualizarlos | Revisión humana para cambios críticos |
| connections.create/patch | Declarar relaciones a bloques existentes o del mismo batch | Resolución de destinos verificable |
| batch.prepare | Combinar N operaciones de creación y modificación | Un único plan con scope y límite |
| batch.apply | Mismo change.apply con el plan compuesto | No crear un bypass del engine |

**Fuera del lote normal o bajo gate especial:** borrar bloques, cambiar UID, aceptar un cambio de intención, desproteger authority, migrar backend y alterar invariantes de seguridad. No convertir una propuesta LLM de propósito en decisión aceptada automáticamente.

### 4A.2. Ejemplo de solicitud (sólo diseño)

    schema: bpfw.change/1
    mode: PREVIEW
    project_ref: proyecto-autorizado
    expected_authority_revision: 42
    idempotency_key: ejemplo-01
    reason: Actualizar las responsabilidades del scheduler
    operations:
      - op: blocks.create
        client_ref: nuevo
        fields: {id: "scheduler::safe_retry::function", domain: scheduler, purpose: "Reintentar sólo lecturas verificadas"}
      - op: blocks.patch
        uid: uid-existente
        expected_entity_revision: 7
        fields: {purpose: "Coordinar sin duplicar efectos"}
      - op: connections.create
        source: {client_ref: nuevo}
        target: {uid: uid-existente}
        relationship: DEPENDS_ON

PREVIEW devuelve plan_id, hash del plan, revisión/digest de authority, operaciones resueltas, diff completo o paginado, bloqueos y aprobaciones necesarias. APPLY exige plan_id + digest + autorización independiente del host, precondiciones vigentes e identidad de solicitud. El client_ref es temporal dentro del lote; no se convierte en UID oficial por confianza en el texto del modelo.

### 4A.3. Condiciones mínimas de seguridad y semántica

1. **Preview por defecto:** crear, editar y batch sólo preparan una propuesta. Aplicación siempre explícita y separada; una skill, PR, prompt o SCEP no conceden permiso.
2. **Una autoridad:** BPFW sigue siendo el único writer de sus declaraciones; consumidores no ejecutan SQL ni editan YAML directamente. Reutilizar BlueprintEngine, AuthorityPatchEngine, AutomationEngine y SqliteAuthorityStore, después de comprobar sus contratos y carencias.
3. **Revisión y locks:** revalidar authority digest/revision, revisiones por entidad, identidad, alcance, protecciones y permisos justo antes de aplicar. La clave de idempotencia se asocia a actor autorizado, scope, payload y revisión.
4. **Atomicidad del batch:** todo-o-nada; SQLite mediante transacción probada y YAML multishard sólo tras pruebas de rollback/recovery. Si no puede garantizarse, bloquear la operación en ese backend en vez de afirmar atomicidad.
5. **Sin duplicación:** retry de create con mismo payload no duplica el bloque; misma idempotency_key con contenido diferente devuelve conflicto. Tras timeout usar change.status/readback para determinar si se aplicó.
6. **Identidades tipadas:** UID no se reasigna silenciosamente; ID duplicado, rutas inválidas, artefactos fuera de raíz, referencias no resueltas y cambios destructivos no autorizados se rechazan.
7. **Semántica de campos:** set, clear, set_if_absent, null y ausencia de campo no son equivalentes. Validar allowlist de operaciones y campos; no aceptar payloads como comandos, consultas SQL ni rutas arbitrarias.
8. **Límites y protección:** máximo de ítems/bytes/tiempo, políticas de archivos y autoría acreditada por host, no por JSON de la solicitud; nunca desbloquear implícitamente authority.
9. **Recibo verificable:** actor, motivo, operaciones, revisión anterior y posterior, before/after digest, conflictos, estado, audit log y readback. El recibo no significa que se verificó el comportamiento del código.
10. **Sin efectos colaterales:** no ejecutar CI, generar código, crear ramas, hacer merge, cambiar Git remoto ni publicar datos sensibles en una operación de authority.
11. **Transportes equivalentes:** CLI JSON primero; si se añade MCP o HTTP, ambos usan la misma aplicación y preservan permisos y semánticas, no ofrecen otra ruta de escritura.
12. **Compatibilidad:** comando no disponible en BPFW Core, SQLite o YAML retorna UNSUPPORTED_CAPABILITY, nunca un fallback silencioso.

Estados propuestos: PLANNED, BLOCKED, NO_OP, APPLIED_READBACK_VERIFIED, REJECTED, CONFLICT, FAILED, UNCERTAIN_RECONCILE. Errores candidatos adicionales: APPROVAL_REQUIRED, PLAN_EXPIRED, PLAN_DIGEST_MISMATCH, REVISION_CONFLICT, LOCKED_AUTHORITY, DUPLICATE_IDENTITY, BATCH_LIMIT, IDEMPOTENCY_CONFLICT, WRITE_STATE_UNKNOWN. Reutilizar los errores existentes si corresponden; ninguno es un contrato aceptado hasta completar Q1/W1.

### 4A.4. Fases de mejora BPFW integradas con Q0–Q7

| Fase | Entregable | Aceptación |
| --- | --- | --- |
| W0 Auditoría AS-IS | Inventariar create/patch/batch por motor y backend; side effects, locks, revisiones, recibos | Tabla de reutilización y fallos reproducibles |
| W1 Contrato de cambios | DTOs, schemas, operaciones, identidad, permisos, límites, errores, idempotencia | Revisión de clientes y pruebas negativas |
| W2 Propuestas y preview | Fachada común que usa los planificadores existentes | No se altera authority ni historial |
| W3 Aplicar unidad | Crear o modificar una declaración con grant de host | Lock/CAS, recibo y readback |
| W4 Batch transaccional | Create+patch+connection y resolución de client_ref | Todo-o-nada, crash/reinicio y concurrencia |
| W5 CLI/MCP/HTTP | CLI JSON versionada primero; MCP/HTTP requieren aprobación propia | Paridad de autorización y comportamiento |
| W6 Consumidores | Dendryte prepara contexto y cambios propuestos; Me permite revisar y aprobar | Ningún LLM o consumidor puede mutar por sí solo |
| W7 Piloto | Proyecto de laboratorio y eventual adopción | Evidencia reproducible y compatibilidad por backend |

W0 se incorpora a Q0; W1 a Q1; W2 requiere el contrato de consulta o snapshots verificables; W3 requiere preview seguro; W4 requiere W3 probado. Dendryte y Me pueden explorar la vista de propuestas, sin implementar escritores redundantes. No se abre otro plan ni otra PR de producto por estas fases.

### 4A.5. Oráculos nuevos, PENDING / NOT_RUN

- T14 Retry de blocks.create con misma clave no duplica; clave reutilizada con payload distinto da conflicto.
- T15 Editar sobre expected_entity_revision obsoleta se rechaza sin modificación.
- T16 Lote de 3 operaciones cuya última falla deja la authority sin cambios.
- T17 Crear bloque y relación mediante client_ref dentro de un batch resuelve la referencia correcta.
- T18 Lock activo o permiso ausente bloquean apply aun cuando un LLM asegure que está aprobado.
- T19 Caída entre commit y respuesta: change.status/readback impide doble aplicación.
- T20 YAML multishard con fallo intermedio demuestra rollback o impide exponer batch.apply.
- T21 SQLite con escritores concurrentes conserva integridad, revisiones y outbox.
- T22 Cambio de purpose no sustituye intención histórica ni garantiza comportamiento del código.
- T23 Campos y rutas fuera de allowlist, cambios UID y SQL malicioso se rechazan.
- T24 Gran batch excede límites sin aplicar un subconjunto.
- T25 CLI y futuros MCP/HTTP se comportan igual ante mismo plan y permisos.
- T26 Dendryte y Me no obtienen poder de escritura por leer el plan o la skill.


## 5. Requisitos de backend y seguridad

**SQLite experimental:** transacción de lectura coherente, conexión de solo lectura donde proceda, consulta parametrizada, sin escritura de journal/PRAGMA mutable; probar WAL, bloqueo concurrente, cursor y cambio de revisión. Nunca usar immutable si falsea lecturas del WAL activo. Comprobar por contenido que la consulta no modifica los recursos protegidos.

**YAML público/compatibilidad:** lectura estricta de los archivos autorizados, con límite; no ejecutar sincronización automática de shards ni unlock. Reutilizar el cargador si se comprueba que no muta; de otro modo crear una ruta de lectura pura.

**API externa:** CLI invocada por argv fijo y ruta canónica bajo permiso del host, sin shell interpolado, cwd/variables controladas, stdout JSON separado de stderr; timeouts. No red ni sockets salvo aprobación posterior. No instalar implícitamente BPFW experimental en proyectos que sólo usan Core.

**Cambios de authority:** fuera de bpfw.query/1, pero dentro del contrato candidato bpfw.change/1 para creaciones, edición de campos y lotes. Requieren preview, validación, permiso de host, CAS/readback, auditoría y gates existentes. Ninguna consulta otorga permisos.

## 6. Consumidores y fronteras

- **BPFW experimental:** dueño de la fachada, normalización de metadata y consulta por backend.
- **BPFW Core público:** puede adoptar sólo un subconjunto que su authority soporte, sin arrastrar Editor/Planner/SQLite experimental ni modificar la superficie pública por este documento.
- **Dendryte Rust (consumidor opcional):** descubre capacidades, llama CLI con control del host, relaciona datos con Git/planes, prepara contexto para el LLM. No incluye código Python ni copia la autoridad BPFW.
- **Me (consumidor indirecto):** utiliza contextos que entrega Dendryte para mostrar intención, riesgo, foco y títulos. No lee directamente tablas internas BPFW ni habilita navegador por esta integración.
- **LLM:** compara propósitos declarados con el objetivo, propone hipótesis y pruebas, pero no modifica propósito ni declara tareas completas sin verificación.

El catálogo de nombres de conversaciones y la intención contextual anterior son propuestas complementarias, no endpoints ni contratos ya instalados.

## 7. Fases y gates

| Fase | Dueño | Entregable | Gate verificable |
| --- | --- | --- | --- |
| Q0 Inventario | BPFW exp. | Mapa operación → función → backend → side effects → datos disponibles | Fuente y prueba reproducible por ruta |
| Q1 Contrato | BPFW exp. | Tipos de entrada/salida, versiones, errores, filtros y seguridad | Revisión de consumidores y casos negativos |
| Q2 Lector mínimo | BPFW exp. | capabilities/snapshot/blocks.list/blocks.get en biblioteca y CLI JSON | Tests por backend y no mutación |
| Q3 Intención/relaciones | BPFW exp. | trace/why/relations y diagnósticos read-only donde haya datos | Proveniencia, límites, historial y stale comprobados |
| Q4 Paridad Core | BPFW público | Evaluar subconjunto compatible sin ampliar Core por defecto | Contrato o UNSUPPORTED explícito; no romper MVP |
| Q5 Adaptador | Dendryte | Consumidor Rust opcional y contexto Git + BPFW | Mismo task_id, snapshot, límites, degradación sin BPFW |
| Q6 Experiencia | Me | Mostrar fuentes/intención y título derivado, sin segundo parser | Componente sin duplicar motor y sin permisos nuevos |
| Q7 Certificación | Propietarios de cada repo | Piloto multiagente y auditoría de permisos/datos | Evidencias postintegración; aprobación por repositorio |
| W0–W7 Cambios controlados | BPFW exp. / consumidores opcionales | Crear, editar y aplicar batch con permisos | Gates separados en §4A, no implementado |

**Dependencias:** Q0 (+W0) → Q1 (+W1) → Q2 → Q3; W2 exige contrato, W3 exige preview validado, W4 exige W3. Q4 puede estudiar la paridad desde Q1. Q5 requiere contrato Q2 validado y es opcional. Q6 depende del adaptador disponible o de una vista equivalente ya existente. Q7 no se cierra por tests simulados.

**Owner:** uno por archivo/PR; reutilizar ramas, relaciones y planes existentes. No tocar módulos en otra PR. Las unidades son propuestas de entregables, no autorización de cambios.

## 8. Pruebas de aceptación (oráculos, no PASS)

- T01 Consulta autorizada no cambia ningún archivo de authority, historial, lock, cache ni árbol Git; medir hashes/estado antes y después.
- T02 Un SQLite en escritura concurrente devuelve un snapshot coherente o STALE; nunca mezcla páginas.
- T03 Authority ausente o UID ambiguo devuelve estado explícito; jamás inventa propósito.
- T04 Proyecto fuera de roots autorizados es rechazado sin leerlo.
- T05 Solicitud con filtros maliciosos no permite SQL injection, traversal ni acceso arbitrario.
- T06 Límite de bytes/páginas/timeouts se impone incluso ante grandes bases.
- T07 Una relación declarada puede citarse; una relación inferida no aparece como VERIFIED.
- T08 La misma consulta con la misma revisión devuelve salida estable, salvo campos explícitamente volátiles.
- T09 La variante pública sin intención experimental devuelve UNSUPPORTED, no caída ni import implícito.
- T10 Dendryte ausente / BPFW ausente: cada producto sigue funcionando de manera independiente.
- T11 Dendryte agrupa contexto por Git SHA + BPFW revision; un origen obsoleto provoca STALE/PARTIAL.
- T12 El LLM mejora una decisión focal con propósito disponible sin cambiar automáticamente autoridad ni plan.
- T13 Me muestra procedencia y advertencias; no afirma acceso a chats web ni los modifica.

## 9. Pilotaje y decisiones pendientes

Elegir una copia de laboratorio con 1–3 bloques reales, relaciones e historial voluntariamente disponible. Comparar una tarea de diseño planificada sólo con Git frente a Git+BPFW: número de restricciones pertinentes recuperadas, errores de identificación, afirmaciones sin fuente, pruebas propuestas y costo de lectura. No inventar porcentajes de mejora.

Decisiones del propietario antes de implementación: admitir query y change; revisar permisos de escritura/creación, scopes, política de locks, semántica de atomicidad por backend e idempotencia; elegir versionado y subconjunto Core, distribución CLI y posible MCP/HTTP; recursos para pruebas/CI. MCP directo o HTTP requieren necesidad y aprobación adicionales.

**NEXT_ACTION:** ejecutar Q0+W0 en bpfw-experimental: inventario read-only de consultas **y** rutas de creación, actualización y batch, revisiones, protección, logs y garantías por backend; después proponer los contratos Q1/W1. No programar escrituras antes de los gates. No crear runtime ni pasar a Q2 sin ese gate.

## 10. Regla de coordinación entre repositorios

ID común: BPFW-READ-API-20261119 (conservado para referencias cruzadas; el alcance ahora incluye también bpfw.change/1). Este documento es la referencia de **contrato del productor BPFW experimental**; los demás repos mantienen sólo una ficha específica de adopción enlazada a esta ruta, no copias ni backlogs nuevos. Los estados de Q0–Q7 se informan desde evidencias de cada repo, no desde este texto. Antes de cualquier implementación: refrescar main/PR/owners, seguir AGENTS/coordination, confirmar SHAs y permisos. Ningún merge, CI pago o despliegue queda autorizado por una PR documental.
