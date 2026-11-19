# BPFW — Contrato de consultas para agentes y herramientas (propuesta V1)

**ID:** BPFW-READ-API-20261119
**Estado:** PROPOSED / NOT_IMPLEMENTED / NOT_APPROVED
**Fecha:** 2026-11-19
**Propietario del contrato:** Blueprint Framework; esta especificación NO autoriza implementar, migrar SQLite, cambiar authority, publicar endpoints, CI de pago o hacer merge.
**Alcance:** biblioteca Python + CLI JSON sin efectos como primera versión; MCP/HTTP son opciones condicionadas a consumidores y pruebas.
**Base inspeccionada:** bpfw-experimental main a4a0b374f71a2e9398e7f78c0569e0633108718f. Revalidar HEAD antes de implementar.

## 1. Problema, objetivo y valor

BPFW mantiene datos sobre unidades de código, su propósito declarado, ubicación, dominio, historial y protección de autoridad. Los agentes externos necesitan consultarlos de forma selectiva, estable, acotada y segura, sin acoplarse a tablas internas SQLite/YAML ni disparar escrituras. Dendryte puede reunirlos con datos Git y planes; un LLM puede formular mejores hipótesis y estrategias, sin que BPFW ni Dendryte ejecuten modelos.

**Promesa medible:** ante un identificador de trabajo y un conjunto de rutas/símbolos, un consumidor recibe bloques, propósitos, relaciones, cambios conocidos, advertencias y procedencia en JSON, mediante lecturas sin efectos y con límites explícitos. Sin BPFW o sin una capacidad, el cliente degrada con honestidad, sin inventar información.

**No objetivos:** convertir BPFW en orquestador de agentes, exportar toda la base de datos, escribir planes de Git en BPFW, duplicar el journal de Dendryte, exponer SQLite crudo, crear un daemon obligatorio ni servir HTTP en la primera entrega.

## 2. Estado actual comprobado y límites

**VERIFIED (fuentes GitHub, no tests en esta intervención):**
- El paquete público blueprint-framework expone Core centrado en init, verify, status, lock, unlock, watch y reshard; su README no promete una API de intención equivalente a experimental.
- bpfw-experimental declara versión 0.3.0 e incluye CLI history, why, trace, intent, batch, authority y consultas JSON en varios comandos.
- src/bpfw/core/history/commands.py contiene trace_location, búsqueda del bloque por ruta/línea y consulta de HistoryLedger.
- src/bpfw/cli.py tiene rutas de consulta del historial, pero el camino verify puede invocar capture_artifact_state; status puede seguir rutas de sincronización de shards. Estos comandos no son un contrato puro de lectura.
- Experimental declara SQLite como authority activa y YAML como snapshot generado; la base pública tiene otra superficie. No asumir equivalencia ni paridad de despliegue.
- Los documentos históricos describen un almacenamiento SQLite, revisiones y operaciones selectivas; su existencia no acredita que todas las rutas del CLI sean aptas para exportación segura.

**PENDING / REQUIRED:** auditoría exacta de side effects e imports, API interna real, cobertura de lenguajes, estabilidad de UID, formato de historial, revisión de authority, compatibilidad de CLI, límites de consultas y pruebas negativas. No clasificar ninguna operación como READ_ONLY_VERIFIED sin test de no mutación.

## 3. Decisión arquitectónica recomendada

Alternativa A (**preferida**): una fachada de consulta dentro de BPFW que usa el backend activo y produce DTOs versionados; CLI JSON como primer transporte, sin servidor. Consumidores externos llaman un ejecutable autorizado por ruta y argumentos predefinidos.

Alternativa B: MCP de BPFW. Útil si otros agentes quieren usar BPFW directamente. Añadirlo solo después del contrato de consulta A y de demostrar un consumidor real; no duplicar lógica.

Alternativa C: REST HTTP local. No incorporarlo inicialmente: sockets, orígenes, autenticación, exposición, concurrencia y nuevos riesgos no se justifican con un consumidor Rust que puede leer la salida JSON de una CLI.

Las tres alternativas podrían compartir la **misma fachada Python de consultas**. Ningún transporte debe acceder directamente a las tablas SQLite ni redefinir semánticas de authority.

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

## 5. Requisitos de backend y seguridad

**SQLite experimental:** transacción de lectura coherente, conexión de solo lectura donde proceda, consulta parametrizada, sin escritura de journal/PRAGMA mutable; probar WAL, bloqueo concurrente, cursor y cambio de revisión. Nunca usar immutable si falsea lecturas del WAL activo. Comprobar por contenido que la consulta no modifica los recursos protegidos.

**YAML público/compatibilidad:** lectura estricta de los archivos autorizados, con límite; no ejecutar sincronización automática de shards ni unlock. Reutilizar el cargador si se comprueba que no muta; de otro modo crear una ruta de lectura pura.

**API externa:** CLI invocada por argv fijo y ruta canónica bajo permiso del host, sin shell interpolado, cwd/variables controladas, stdout JSON separado de stderr; timeouts. No red ni sockets salvo aprobación posterior. No instalar implícitamente BPFW experimental en proyectos que sólo usan Core.

**Cambios de authority:** fuera de alcance; cualquier futuro write API requiere propuesta/preview, revisión, permisos, CAS/readback y gates de BPFW. Consultar nunca otorga permiso de escritura.

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

**Dependencias:** Q0 → Q1 → Q2 → Q3. Q4 puede estudiar la paridad desde Q1. Q5 requiere contrato Q2 validado y es opcional. Q6 depende del adaptador disponible o de una vista equivalente ya existente. Q7 no se cierra por tests simulados.

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

Decisiones del propietario antes de implementación: admitir nueva familia query; elegir versionado y subconjunto Core; mecanismo de distribución CLI; política de publicación de snapshots derivados; recursos y permisos para pruebas/CI. MCP directo o HTTP requieren necesidad y aprobación adicionales.

**NEXT_ACTION:** ejecutar Q0 en bpfw-experimental: inventario read-only por función/consumidor, demostración de qué se puede consultar sin mutar, y proponer contrato final de Q1. No crear runtime ni pasar a Q2 sin ese gate.

## 10. Regla de coordinación entre repositorios

ID común: BPFW-READ-API-20261119. Este documento es la referencia de **contrato del productor BPFW experimental**; los demás repos mantienen sólo una ficha específica de adopción enlazada a esta ruta, no copias ni backlogs nuevos. Los estados de Q0–Q7 se informan desde evidencias de cada repo, no desde este texto. Antes de cualquier implementación: refrescar main/PR/owners, seguir AGENTS/coordination, confirmar SHAs y permisos. Ningún merge, CI pago o despliegue queda autorizado por una PR documental.
