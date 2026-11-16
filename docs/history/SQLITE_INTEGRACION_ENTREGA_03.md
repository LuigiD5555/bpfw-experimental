# Local BPFW correction: 0.2.0a14.post3

This revision is based on the supplied post2 source distribution. The original distribution is preserved.

## Corrections

- Artifact resolution reuses the existing Python source repository and its qualified-symbol index. A method belonging to one class cannot resolve to another class because of a stale stored line.
- Python and optional grammar parsing is shared across artifacts of the same file during one resolver run.
- History captures and SQLite outbox operations persist events and content objects in durable JSON batches with one index transaction. Existing individual events remain readable; index reconstruction restores both formats and content-addressed objects. Failed in-memory batches publish no partial events.
- CLI verification captures artifact history once. History capture shares Git context and connection-graph work while retaining artifact events and unchanged-state detection.
- Explicit Python declarations are resolved even when default discovery filters exclude a private helper, exception, protocol or data-only class. Source roots, ignore rules and symbol kinds still apply.
- Repeated HTML IDs in mutually exclusive template branches receive distinct native identities. Child ownership remains explicit.
- Generic API names, process runners, loggers, placeholder resource names, shared templates and read-only SQL are not sufficient to establish a hard duplicate responsibility. Concrete writes, SQL mutations, HTTP route ownership and explicit identical purposes retain blocking checks.
- Native module/unit identifiers and unevaluated template variables are descriptive metadata. Embedded literal credentials and absolute filesystem locations remain subject to security validation.

## Validation

The source suite passes 80 tests and 51 subtests with optional grammar packages installed. Regression tests cover qualified ownership, parser reuse, history event completeness, one CLI capture, private declarations, source scope, conditional HTML identities, security false positives and retained blocking checks.

Extracta's catalog is synchronized separately through its SQLite engine. Existing human purpose, intent, lifecycle and contract annotations are preserved; newly discovered units are explicitly marked as inferred source declarations. Only one physically absent declaration is retired. The copied lifecycle-preflight purpose is corrected to describe its read-only diagnostic responsibility.

The previous SQLite limitations in [post2](SQLITE_INTEGRACION_ENTREGA_02.md) still apply. This is a local correction, not an upstream production certification.
