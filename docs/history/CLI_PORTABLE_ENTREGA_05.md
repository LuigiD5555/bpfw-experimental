# BPFW 0.2.0a14.post5 — Explorador CLI desacoplado

**Base:** post4 corregida del 19 de octubre de 2026. **Entrega:** refactor del motor CLI sin doble Editor ni backend paralelo.

## 1. Resultado

El motor de interacción (`bpfw.integrations.shared.cli_explorer`) ya no importa SQLite, AuthorityQueries, Blueprint Engine, Inspector, ni nombres de tablas o campos de Blueprint. Se utiliza el mismo `BrowserController` para (a) proyectos BPFW con SQLite y (b) un catálogo arbitrario en memoria de un dominio independiente. Cada adaptador decide qué consultar, cómo identificar los registros, qué campos expone, cómo revisar/aplicar cambios y cuáles operaciones admite.

### Dependencias (unidireccionales)

```text
BPFW CLI --project-root PATH
       |
       v
core.authority.sqlite.editor.run_editor
       |
       v
BpfwExplorerAdapter ----------------> AuthorityQueries --> SQLite del proyecto
       |                                      |
       |                                      +--> solamente proyecciones/páginas
       +-- preview/apply --> BlueprintEngine --> SQLite transaccional
       +-- inspect -----> Inspector
       +-- relations/history/diagnostics/export --> SQLite
       |
       v
BrowserController <--- ExplorerAdapter (contrato de 17 métodos/propiedades)
       |
       +-- ExplorerQuery / ExplorerPage / BrowserState (efímeros)
       +-- catalogue/details/render_value (presentación adaptativa)
       +-- selección UID+revisión / previsualización / confirmación

Otros consumidores -> ExplorerRegistry -> MemoryExplorerAdapter / otros adaptadores
                         |
                         +--> nuevo BrowserController por fuente
```

El motor reutilizable **no** gestiona conexiones, permisos de Blueprint ni autenticación de un proyecto. Esas responsabilidades pertenecen al adaptador del dominio. La elección de raíz de BPFW se conserva en `--project-root`; no hay rutas fijas ni estado global entre proyectos.

## 2. Inventario de código

| Archivo | Responsabilidad |
| --- | --- |
| `src/bpfw/integrations/shared/cli_explorer/models.py` | `ExplorerQuery`, `ExplorerPage` y `ExplorerAdapter` (contrato) |
| `.../controller.py` | Único estado de navegación y motor de comandos, sin dependencia del dominio |
| `.../presentation.py` | Anchos Unicode, truncamiento seguro, tabla/ficha/render JSON genéricos |
| `.../registry.py` | Registro de fábricas de fuentes por nombre, instancia por proyecto |
| `.../memory_adapter.py` | Adaptador no SQLite para un catálogo arbitrario, lectura/filtrado/CSV/JSON |
| `src/bpfw/core/authority/sqlite/explorer_adapter.py` | Implementación del contrato específica de BPFW; consultas, validación, historial, Inspector y Blueprint Engine |
| `src/bpfw/core/authority/sqlite/editor.py` | Punto único de entrada para Editor interactivo y scripts, crea el adaptador BPFW |
| `src/bpfw/core/authority/sqlite/commands.py` | Perfil BPFW también para la salida no interactiva, sin copiar tablas ni renderizadores |
| `tests/test_portable_explorer.py` | Aislamiento entre raíces; adaptador no BPFW; registro; exportación segura; recuperación tras cambio |
| `tests/test_cli_explorer.py` | Flujos reales de Editor y SQLite, adaptados al contrato nuevo |

La vista YAML anterior no se reintroduce. La migración YAML→SQLite es una operación de conversión de datos, no otro editor.

## 3. Contrato para crear un adaptador nuevo

Un adaptador define `identity`, `title`, `default_sort`, `profiles`, `labels`, `fields`, `sortable`, `groupable`, `editable`, `detail_fields` y `section_fields`.

Implementa:

- `page(query, after)`: página pequeña y cursor opaco; la revisión de la fuente impide seguir un cursor obsoleto.
- `get(id)`: documento completo **solamente** cuando el usuario abre una ficha y su revisión.
- `resolve(ids)` / `matching(query)`: registros ligeros con `uid` y `entity_revision` para selección estable, límite 10 000.
- `facets(query, field)`: agregación por campo solicitado, manteniendo filtros vigentes.
- `relations(id)`, `history(id)`, `issues()`: información específica del dominio a demanda.
- `preview(patches)` / `apply(patches)`: validación y transacción propias del adaptador; nunca escrita por el navegador.
- `inspect(id, input, output)`: acción contextual opcional; adaptadores sin inspector deben informar que no está disponible.
- `export(query, fmt, destination)`: exportación completa de registros consultados sin perder campos por truncamiento visual.

Las filas ligeras se normalizan a `uid` y `entity_revision` aunque en el origen físico tengan otras claves. El motor sólo conoce **estos dos atributos contractuales**, no nombres, IDs o estructuras de autoridad BPFW.

### Ejemplo de otro dominio

```python
from bpfw.integrations.shared.cli_explorer import BrowserController, ExplorerRegistry
from bpfw.integrations.shared.cli_explorer.memory_adapter import MemoryExplorerAdapter

registry = ExplorerRegistry()
registry.register('orders', lambda rows: MemoryExplorerAdapter(
    rows, identity='orders/warehouse-2', key='order_no', title='ORDERS',
    profiles={'short': ('order_no', 'customer', 'status')}))

adapter = registry.create('orders', rows=[
    {'order_no': 'A001', 'customer': 'Ada', 'status': 'open'},
    {'order_no': 'A002', 'customer': 'Lin', 'status': 'done'},
])
BrowserController(adapter).run()
```

`MemoryExplorerAdapter` es deliberadamente solo de lectura: permitir escritura arbitraria sin validadores ni transacciones específicos del dominio sería inseguro. Es una demostración funcional de reutilización, no un almacenamiento alternativo de Blueprint. Cuando el volumen sea grande, usar un adaptador con paginación y filtros *pushdown* como el de SQLite.

## 4. Ciclos operativos

**A. Consulta interactiva:** CLI resuelve la raíz → Editor instancia `BpfwExplorerAdapter(SqliteAuthorityStore(root))` → `BrowserController.page` pide sólo columnas indexadas → `catalogue` presenta columnas del perfil del adaptador → `open` obtiene el documento y la revisión → `back` regresa sin perder los filtros.

**B. Edición:** Selección por UID+revisión → `edit` construye parches sin escribir → `review` llama al adaptador BPFW y de allí a Blueprint Engine → `apply` exige confirmar literalmente `APPLY` → Engine valida revisiones y protección, y confirma transacción o falla sin dejar cambios parciales. El motor genérico no conoce SQL ni llama al repositorio directamente.

**C. Cambio concurrente:** un cursor de SQLite con revisión obsoleta produce conflicto; adaptador traduce a error genérico de navegación, la sesión reinicia su página sin alterar las revisiones de la selección. Al revisar parches basados en revisiones antiguas, Engine los rechaza; el navegador no actualiza revisiones en secreto.

**D. Uso en múltiples proyectos:** dos invocaciones con `--project-root` distintos abren bases independientes. `ExplorerRegistry.create` produce objetos nuevos sin caches compartidas; crear dos controladores conserva selecciones/columnas/filtros aislados, incluso cuando ambas bases contienen el mismo UID.

**E. Exportación:** la operación delega al adaptador. SQLite usa snapshot de lectura, lotes y archivo temporal junto al destino; solo publica el archivo terminado. El adaptador de memoria limita cantidad y neutraliza fórmulas CSV. El navegador no emite como exportación los textos truncados de las tablas.

## 5. Compatibilidad de comandos

Conservados en el Editor: `n`, `p`, `b`, `q`, `?`, `open`, búsqueda `/`, `f`, `sort`, `group`, `cols`, `view`, `m`, `selected`, `edit`, `clear`, `review`, `apply`, `detail`, `relations`, `history`, `issues`, `inspect`, `export csv|json`. Los alias y confirmación permanecen. El prompt interactivo común es `explorer>`.

```sh
bpfw editor --project-root /ruta/proyecto-a
bpfw editor --project-root /ruta/proyecto-b --search validator --json
bpfw editor --project-root /ruta/proyecto-a --all --set status=deprecated  # preview
bpfw editor --project-root /ruta/proyecto-a --all --set status=deprecated --apply
```

## 6. Pruebas y límites

Pruebas ejecutadas: `tests/test_portable_explorer.py`, `test_cli_explorer.py`, `test_sqlite_authority.py`, `test_sqlite_full_integration.py`, `test_editor_workflow.py`, `test_duplicate_groups.py`, `test_security_metadata.py`. **77 tests + 45 subtests aprobados** en el entorno de trabajo. El conjunto total del repositorio tiene pruebas que no se pudieron recolectar por faltar `pytest_readable` en este entorno; no se informa como suite completa aprobada.

No se reemplazaron íntegramente las sesiones particulares de Planner, Drift Gate ni Inspector: mantienen su lógica de decisiones y se integran con este Editor mediante el adaptador explícito. Este cambio desacopla completamente **el motor CLI exploratorio**, no certifica todas las pantallas de BPFW como independientes ni convierte la biblioteca CLI en una distribución Python separada. Las pruebas sobre los proyectos reales grandes aún deben ejecutarse antes de declararlo listo para producción.

## 7. Comprobaciones obligatorias para quien continúe

1. Mantener los imports del paquete compartido libres de `bpfw.core.*`, de Inspector y de SQLite.
2. No añadir nuevos editores o ciclos de navegación paralelos para cada backend.
3. No escribir directamente desde `BrowserController`, ni permitir `apply` sin `review` + confirmación.
4. Garantizar `uid` estable y `entity_revision` antes de implementar selección o cambios.
5. Probar aislamientos de raíz, cambios concurrentes, salida no interactiva, anchos de terminal y exportación segura.
6. Considerar imposible un rollback de autoridad a partir de la simple navegación: restaura únicamente mediante los mecanismos de History/Engine.
