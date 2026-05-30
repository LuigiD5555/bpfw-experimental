"""Observable outcome analysis for catalog verification."""

import ast
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from bpfw.core.catalog.models import DiscoveredCodeUnit
from bpfw.reports.finding import FINDING_SEVERITY_WARNING, Finding

_SOURCE = "bpfw"
_SAME_OUTCOME = "SAME_OUTCOME"
_SIMILAR_OUTCOME = "SIMILAR_OUTCOME"
_CONFLICTING_EFFECT = "CONFLICTING_EFFECT"
_UNCLASSIFIED_EXTERNAL_EFFECT = "UNCLASSIFIED_EXTERNAL_EFFECT"
_FUNCTION_TYPES = {"function", "method", "nested_function"}

_PERSISTENT_OR_EXTERNAL_RESOURCES = {
    "audio_stream",
    "browser_page",
    "cache",
    "container",
    "database",
    "dataset",
    "device",
    "directory",
    "environment",
    "file",
    "gpio_pin",
    "http_api",
    "image",
    "log",
    "message_queue",
    "metric",
    "midi_event",
    "model",
    "model_artifact",
    "process",
    "serial_port",
    "socket",
    "terminal",
}

_HIGH_SIGNAL_ACTIONS = {
    "authorize",
    "click",
    "commit",
    "compile",
    "configure",
    "connect",
    "consume",
    "create",
    "delete",
    "deploy",
    "emit",
    "execute",
    "flash",
    "insert",
    "play",
    "predict",
    "publish",
    "read",
    "receive",
    "record",
    "render",
    "send",
    "start",
    "stop",
    "train",
    "transform",
    "update",
    "validate",
    "write",
}

_OPPOSITE_ACTIONS = {
    ("start", "stop"),
    ("connect", "disconnect"),
    ("create", "delete"),
    ("insert", "delete"),
    ("lock", "unlock"),
    ("enable", "disable"),
    ("play", "stop"),
}

_BUILTIN_CALLS = {
    "all",
    "any",
    "bool",
    "dict",
    "enumerate",
    "filter",
    "float",
    "int",
    "isinstance",
    "len",
    "list",
    "map",
    "max",
    "min",
    "range",
    "repr",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
    "zip",
}


@dataclass(frozen=True)
class ObservedEffect:
    """Represent one visible effect inferred from a code block.

    Attributes:
        action: Verb describing the visible action, such as write, insert, send, or train.
        resource_kind: Generic resource affected by the action.
        target: Best-effort target name or pattern when it can be inferred.
        input_kind: Best-effort description of the input consumed by the action.
        output_kind: Best-effort description of the output produced by the action.
        confidence: Confidence level for the inferred effect.
        evidence: Human-readable evidence that explains why the effect was inferred.
    """

    action: str
    resource_kind: str
    target: str | None = None
    input_kind: str | None = None
    output_kind: str | None = None
    confidence: str = "medium"
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def comparable_key(self) -> str:
        """Return a stable key used to compare observable outcomes."""
        return "|".join(
            [
                self.action,
                self.resource_kind,
                self.target or "*",
                self.output_kind or "*",
            ]
        )

    def broad_key(self) -> str:
        """Return a broader key for related-outcome comparison."""
        return "|".join([self.action, self.resource_kind])


@dataclass(frozen=True)
class OutcomeFingerprint:
    """Summarize the observable result of one code unit."""

    unit: DiscoveredCodeUnit
    effects: tuple[ObservedEffect, ...]
    calls: tuple[str, ...]
    returns_value: bool
    raises: tuple[str, ...]
    mutations: tuple[str, ...]

    def primary_effect(self) -> ObservedEffect | None:
        """Return the most important observable effect for comparison."""
        if not self.effects:
            return None
        ranked_effects = sorted(self.effects, key=_effect_priority, reverse=True)
        return ranked_effects[0]


@dataclass(frozen=True)
class _IndexedNode:
    """Store an AST node together with source text."""

    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
    source_text: str


class CodeOutcomeAnalyzer:
    """Analyze code blocks by their observable effects rather than their declared purposes."""

    def __init__(self, project_root: Path, discovered_units: list[DiscoveredCodeUnit]) -> None:
        """Initialize the analyzer.

        Args:
            project_root: Project root containing the source files.
            discovered_units: Code units discovered by the catalog scanner.
        """
        self.project_root = project_root
        self.discovered_units = discovered_units
        self._node_index_by_path: dict[str, dict[str, _IndexedNode]] = {}

    def analyze(self) -> list[Finding]:
        """Detect duplicate, similar, conflicting, and unknown observable outcomes."""
        fingerprints = self._build_fingerprints()
        findings: list[Finding] = []
        findings.extend(self._find_same_outcomes(fingerprints))
        findings.extend(self._find_similar_outcomes(fingerprints))
        findings.extend(self._find_conflicting_effects(fingerprints))
        return findings

    def _build_fingerprints(self) -> list[OutcomeFingerprint]:
        """Build observable-effect fingerprints for every function-like code unit."""
        fingerprints: list[OutcomeFingerprint] = []
        for unit in self.discovered_units:
            if unit.symbol_type not in _FUNCTION_TYPES:
                continue
            indexed_node = self._indexed_node_for_unit(unit)
            if indexed_node is None:
                continue
            node = indexed_node.node
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            facts = _FunctionFacts.from_node(node)
            effects = _infer_effects(unit=unit, facts=facts)
            fingerprints.append(
                OutcomeFingerprint(
                    unit=unit,
                    effects=tuple(effects),
                    calls=tuple(sorted(facts.call_names)),
                    returns_value=facts.returns_value,
                    raises=tuple(sorted(facts.raises)),
                    mutations=tuple(sorted(facts.mutations)),
                )
            )
        return fingerprints

    def _find_same_outcomes(self, fingerprints: list[OutcomeFingerprint]) -> list[Finding]:
        """Find code blocks that share the same high-confidence primary outcome."""
        grouped: dict[str, list[tuple[OutcomeFingerprint, ObservedEffect]]] = {}
        for fingerprint in fingerprints:
            primary_effect = fingerprint.primary_effect()
            if primary_effect is None:
                continue
            if not _is_comparable_effect(primary_effect):
                continue
            if primary_effect.target is None and primary_effect.action not in {"train", "predict", "render", "execute"}:
                continue
            grouped.setdefault(primary_effect.comparable_key(), []).append((fingerprint, primary_effect))

        findings: list[Finding] = []
        for group in grouped.values():
            if len(group) < 2:
                continue
            if _all_units_are_related_interface_methods([item[0] for item in group]):
                continue
            first_fingerprint, first_effect = group[0]
            findings.append(
                Finding(
                    source=_SOURCE,
                    code=_SAME_OUTCOME,
                    severity=FINDING_SEVERITY_WARNING,
                    path=first_fingerprint.unit.path,
                    symbol=first_fingerprint.unit.symbol,
                    message="More than one code block appears to produce the same observable outcome.",
                    evidence=_outcome_evidence(group, first_effect, "high"),
                )
            )
        return findings

    def _find_similar_outcomes(self, fingerprints: list[OutcomeFingerprint]) -> list[Finding]:
        """Find code blocks with the same action/resource pair but weaker target evidence."""
        grouped: dict[str, list[tuple[OutcomeFingerprint, ObservedEffect]]] = {}
        for fingerprint in fingerprints:
            primary_effect = fingerprint.primary_effect()
            if primary_effect is None:
                continue
            if not _is_comparable_effect(primary_effect):
                continue
            if primary_effect.target is not None:
                continue
            if primary_effect.resource_kind not in _PERSISTENT_OR_EXTERNAL_RESOURCES:
                continue
            grouped.setdefault(primary_effect.broad_key(), []).append((fingerprint, primary_effect))

        findings: list[Finding] = []
        for group in grouped.values():
            if len(group) < 2:
                continue
            if len(group) > 8:
                continue
            if _all_units_are_related_interface_methods([item[0] for item in group]):
                continue
            first_fingerprint, first_effect = group[0]
            findings.append(
                Finding(
                    source=_SOURCE,
                    code=_SIMILAR_OUTCOME,
                    severity=FINDING_SEVERITY_WARNING,
                    path=first_fingerprint.unit.path,
                    symbol=first_fingerprint.unit.symbol,
                    message="More than one code block appears to produce a similar observable outcome.",
                    evidence=_outcome_evidence(group, first_effect, "medium"),
                )
            )
        return findings

    def _find_conflicting_effects(self, fingerprints: list[OutcomeFingerprint]) -> list[Finding]:
        """Find blocks that target the same resource with opposite actions."""
        by_resource: dict[str, list[tuple[OutcomeFingerprint, ObservedEffect]]] = {}
        for fingerprint in fingerprints:
            for effect in fingerprint.effects:
                if effect.target is None:
                    continue
                key = "|".join([effect.resource_kind, effect.target])
                by_resource.setdefault(key, []).append((fingerprint, effect))

        findings: list[Finding] = []
        seen_pairs: set[str] = set()
        for group in by_resource.values():
            for left_index, (left_fingerprint, left_effect) in enumerate(group):
                for right_fingerprint, right_effect in group[left_index + 1 :]:
                    if not _actions_conflict(left_effect.action, right_effect.action):
                        continue
                    pair_key = _stable_pair_key(left_fingerprint.unit, right_fingerprint.unit, left_effect.target or "")
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)
                    findings.append(
                        Finding(
                            source=_SOURCE,
                            code=_CONFLICTING_EFFECT,
                            severity=FINDING_SEVERITY_WARNING,
                            path=left_fingerprint.unit.path,
                            symbol=left_fingerprint.unit.symbol,
                            message="Two code blocks appear to apply conflicting actions to the same resource.",
                            evidence={
                                "confidence": "medium",
                                "action": f"{left_effect.action} vs {right_effect.action}",
                                "resource_kind": left_effect.resource_kind,
                                "target": left_effect.target,
                                "units": [_unit_label(left_fingerprint.unit), _unit_label(right_fingerprint.unit)],
                                "effects": [_effect_label(left_effect), _effect_label(right_effect)],
                            },
                        )
                    )
        return findings

    def _find_unclassified_external_effects(self, fingerprints: list[OutcomeFingerprint]) -> list[Finding]:
        """Find unknown calls that probably touch external systems but lack a classifier."""
        findings: list[Finding] = []
        for fingerprint in fingerprints:
            unknown_calls = sorted(_unknown_external_calls(fingerprint.calls))
            if not unknown_calls:
                continue
            findings.append(
                Finding(
                    source=_SOURCE,
                    code=_UNCLASSIFIED_EXTERNAL_EFFECT,
                    severity=FINDING_SEVERITY_WARNING,
                    path=fingerprint.unit.path,
                    symbol=fingerprint.unit.symbol,
                    message="This code block calls an external-looking API that BPFW cannot classify yet.",
                    evidence={
                        "unit": _unit_label(fingerprint.unit),
                        "calls": unknown_calls[:8],
                    },
                )
            )
        return findings

    def _indexed_node_for_unit(self, unit: DiscoveredCodeUnit) -> _IndexedNode | None:
        """Return the AST node that corresponds to a discovered code unit."""
        if unit.path not in self._node_index_by_path:
            self._node_index_by_path[unit.path] = self._build_node_index(unit.path)
        return self._node_index_by_path[unit.path].get(unit.symbol)

    def _build_node_index(self, relative_path: str) -> dict[str, _IndexedNode]:
        """Build a symbol-to-node index for one Python file."""
        source_path = self.project_root / relative_path
        try:
            source_text = source_path.read_text(encoding="utf-8")
            tree = ast.parse(source_text, filename=str(source_path))
        except (FileNotFoundError, UnicodeDecodeError, SyntaxError):
            return {}

        indexed_nodes: dict[str, _IndexedNode] = {}

        def visit_child_nodes(nodes: list[ast.stmt], parent_symbols: list[str]) -> None:
            for node in nodes:
                if isinstance(node, ast.ClassDef):
                    symbol = ".".join(parent_symbols + [node.name])
                    indexed_nodes[symbol] = _IndexedNode(node=node, source_text=source_text)
                    visit_child_nodes(node.body, parent_symbols + [node.name])
                    continue
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbol = ".".join(parent_symbols + [node.name])
                    indexed_nodes[symbol] = _IndexedNode(node=node, source_text=source_text)
                    visit_child_nodes(node.body, parent_symbols + [node.name])

        visit_child_nodes(tree.body, [])
        return indexed_nodes


@dataclass(frozen=True)
class _FunctionFacts:
    """Store raw facts extracted from one Python function or method."""

    call_names: frozenset[str]
    return_descriptions: tuple[str, ...]
    returns_value: bool
    raises: frozenset[str]
    mutations: frozenset[str]
    string_constants: tuple[str, ...]
    argument_names: tuple[str, ...]

    @classmethod
    def from_node(cls, node: ast.FunctionDef | ast.AsyncFunctionDef) -> "_FunctionFacts":
        """Extract simple static facts from a function or method AST node."""
        call_names: set[str] = set()
        return_descriptions: list[str] = []
        raises: set[str] = set()
        mutations: set[str] = set()
        string_constants: list[str] = []

        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                call_name = _call_name(child.func)
                if call_name is not None:
                    call_names.add(call_name)
            elif isinstance(child, ast.Return):
                if child.value is not None:
                    return_descriptions.append(_describe_expression(child.value))
            elif isinstance(child, ast.Raise):
                if child.exc is not None:
                    raises.add(_describe_expression(child.exc))
            elif isinstance(child, ast.Assign):
                for target in child.targets:
                    mutation = _mutation_target(target)
                    if mutation is not None:
                        mutations.add(mutation)
            elif isinstance(child, ast.AnnAssign):
                mutation = _mutation_target(child.target)
                if mutation is not None:
                    mutations.add(mutation)
            elif isinstance(child, ast.AugAssign):
                mutation = _mutation_target(child.target)
                if mutation is not None:
                    mutations.add(mutation)
            elif isinstance(child, ast.Constant) and isinstance(child.value, str):
                string_constants.append(child.value)

        argument_names = tuple(argument.arg for argument in node.args.args)
        return cls(
            call_names=frozenset(call_names),
            return_descriptions=tuple(return_descriptions),
            returns_value=bool(return_descriptions),
            raises=frozenset(raises),
            mutations=frozenset(mutations),
            string_constants=tuple(string_constants),
            argument_names=argument_names,
        )


def _infer_effects(unit: DiscoveredCodeUnit, facts: _FunctionFacts) -> list[ObservedEffect]:
    """Infer observable effects from raw static facts."""
    effects: list[ObservedEffect] = []
    for call_name in facts.call_names:
        effects.extend(_effects_from_call(call_name, facts))
    effects.extend(_effects_from_strings(facts))
    effects.extend(_effects_from_returns(facts))
    effects.extend(_effects_from_raises(facts))
    effects.extend(_effects_from_mutations(facts))
    return _deduplicate_effects(effects)


def _effects_from_call(call_name: str, facts: _FunctionFacts) -> list[ObservedEffect]:
    """Return effects implied by one call name."""
    lower_name = call_name.lower()
    effects: list[ObservedEffect] = []

    # Filesystem and serialization.
    if lower_name.endswith(".write_text") or lower_name in {"write", "writelines"}:
        effects.append(_effect("write", "file", call_name, evidence=f"call {call_name}"))
    if lower_name.endswith(".read_text") or lower_name in {"read", "readlines"}:
        effects.append(_effect("read", "file", call_name, evidence=f"call {call_name}"))
    if lower_name.endswith(".unlink") or lower_name.endswith(".remove") or lower_name.endswith(".rmtree"):
        effects.append(_effect("delete", "file", call_name, evidence=f"call {call_name}"))
    if lower_name.endswith(".mkdir") or lower_name.endswith(".makedirs"):
        effects.append(_effect("create", "directory", call_name, evidence=f"call {call_name}"))
    if lower_name.endswith(".rename") or lower_name.endswith(".move") or lower_name in {"os.replace", "pathlib.path.replace"}:
        effects.append(_effect("move", "file", call_name, evidence=f"call {call_name}"))
    if lower_name in {"open", "path.open"}:
        effects.append(_effect("access", "file", call_name, evidence=f"call {call_name}"))
    if lower_name in {"json.dump", "json.dumps"}:
        effects.append(_effect("serialize", "json", "json", evidence=f"call {call_name}"))
    if lower_name in {"json.load", "json.loads"}:
        effects.append(_effect("parse", "json", "json", evidence=f"call {call_name}"))
    if lower_name in {"yaml.dump", "yaml.safe_dump"}:
        effects.append(_effect("serialize", "yaml", "yaml", evidence=f"call {call_name}"))
    if lower_name in {"yaml.load", "yaml.safe_load"}:
        effects.append(_effect("parse", "yaml", "yaml", evidence=f"call {call_name}"))

    # Database and cache.
    if lower_name.endswith(".execute") or lower_name.endswith(".executemany"):
        effects.append(_sql_effect_from_strings(call_name, facts))
    if lower_name.endswith(".commit"):
        effects.append(_effect("commit", "database", call_name, evidence=f"call {call_name}"))
    if lower_name.endswith(".rollback"):
        effects.append(_effect("rollback", "database", call_name, evidence=f"call {call_name}"))
    if (lower_name.endswith(".add") or lower_name.endswith(".bulk_save_objects")) and any(
        part in lower_name for part in ("session", "query", "db", "database", "repository")
    ):
        effects.append(_effect("insert", "database", call_name, evidence=f"call {call_name}"))
    if lower_name.endswith(".delete") and any(part in lower_name for part in ("session", "query", "db", "database")):
        effects.append(_effect("delete", "database", call_name, evidence=f"call {call_name}"))
    if lower_name.endswith(".query") or lower_name.endswith(".filter") or lower_name.endswith(".select"):
        effects.append(_effect("read", "database", call_name, evidence=f"call {call_name}"))
    if any(marker in lower_name for marker in ("redis", "cache")):
        effects.extend(_cache_effects(call_name, lower_name))

    # HTTP and messaging.
    if lower_name.endswith(('.get', '.post', '.put', '.delete', '.patch')) and any(
        marker in lower_name for marker in ("requests", "httpx", "aiohttp", "http_client", "api_client")
    ):
        action = lower_name.rsplit('.', 1)[-1]
        effects.append(_effect("send", "http_api", action, evidence=f"call {call_name}"))
    if lower_name.endswith(".request"):
        effects.append(_effect("send", "http_api", call_name, evidence=f"call {call_name}"))
    if lower_name.endswith(".publish") or lower_name.endswith(".send") or lower_name.endswith(".put"):
        if any(marker in lower_name for marker in ("queue", "kafka", "sqs", "producer", "broker")):
            effects.append(_effect("publish", "message_queue", call_name, evidence=f"call {call_name}"))
    if lower_name.endswith(".consume") or lower_name.endswith(".receive") or lower_name.endswith(".get"):
        if any(marker in lower_name for marker in ("queue", "kafka", "sqs", "consumer", "broker")):
            effects.append(_effect("consume", "message_queue", call_name, evidence=f"call {call_name}"))

    # Processes and containers.
    if lower_name in {"subprocess.run", "subprocess.call", "subprocess.check_call", "subprocess.check_output", "subprocess.popen"}:
        effects.append(_effect("execute", "process", call_name, evidence=f"call {call_name}"))
    if any(marker in lower_name for marker in ("docker", "container", "containers")):
        effects.extend(_container_effects(call_name, lower_name))

    # Browser, UI, and terminal.
    if lower_name.endswith(".click"):
        effects.append(_effect("click", "browser_page", call_name, evidence=f"call {call_name}"))
    if lower_name.endswith(".send_keys") or lower_name.endswith(".fill") or lower_name.endswith(".type"):
        effects.append(_effect("write", "browser_page", call_name, evidence=f"call {call_name}"))
    if lower_name.endswith(".goto") or lower_name.endswith(".get") and "driver" in lower_name:
        effects.append(_effect("navigate", "browser_page", call_name, evidence=f"call {call_name}"))
    if lower_name in {"print", "input"}:
        action = "read" if lower_name == "input" else "render"
        effects.append(_effect(action, "terminal", call_name, evidence=f"call {call_name}"))
    if "render" in lower_name or "display" in lower_name:
        effects.append(_effect("render", "ui", call_name, evidence=f"call {call_name}"))

    # Hardware, embedded, audio, ML, data.
    if any(marker in lower_name for marker in ("gpio", "digitalwrite", "analogwrite", "pinmode")):
        effects.append(_effect("write", "gpio_pin", call_name, evidence=f"call {call_name}"))
    if "serial" in lower_name:
        action = "read" if lower_name.endswith(".read") else "write" if lower_name.endswith(".write") else "access"
        effects.append(_effect(action, "serial_port", call_name, evidence=f"call {call_name}"))
    if any(marker in lower_name for marker in ("stream.write", "audio", "sound", "midi", "play")):
        effects.extend(_audio_effects(call_name, lower_name))
    if lower_name.endswith(".fit") or lower_name.endswith(".fit_transform") or lower_name.endswith(".train"):
        effects.append(_effect("train", "model", call_name, evidence=f"call {call_name}"))
    if lower_name.endswith(".predict") or lower_name.endswith(".infer"):
        effects.append(_effect("predict", "model", call_name, evidence=f"call {call_name}"))
    if lower_name.endswith(".transform"):
        effects.append(_effect("transform", "dataset", call_name, evidence=f"call {call_name}"))
    if lower_name.endswith(".score") or lower_name.endswith(".evaluate"):
        effects.append(_effect("evaluate", "model", call_name, evidence=f"call {call_name}"))
    if "pandas" in lower_name or lower_name.startswith("pd.") or lower_name.startswith("dataframe."):
        effects.append(_effect("transform", "dataset", call_name, evidence=f"call {call_name}"))

    # Logs, metrics, findings, exceptions.
    if any(lower_name.endswith(f".{method}") for method in ("debug", "info", "warning", "error", "exception", "critical")):
        effects.append(_effect("emit", "log", call_name, evidence=f"call {call_name}"))
    if "metric" in lower_name or lower_name.endswith(".increment") or lower_name.endswith(".gauge"):
        effects.append(_effect("emit", "metric", call_name, evidence=f"call {call_name}"))
    if lower_name.endswith("findings.append"):
        effects.append(_effect("emit", "finding", _finding_code_from_strings(facts), evidence=f"call {call_name}"))
    return effects


def _effects_from_strings(facts: _FunctionFacts) -> list[ObservedEffect]:
    """Infer effects from important string constants."""
    effects: list[ObservedEffect] = []
    for value in facts.string_constants:
        lower_value = value.lower().strip()
        if lower_value.startswith(("insert ", "update ", "delete ", "select ")):
            effects.append(_sql_effect_from_text(value, evidence="sql string"))
        # Plain HTTP method strings are too ambiguous without a nearby HTTP client call.
    return effects


def _effects_from_returns(facts: _FunctionFacts) -> list[ObservedEffect]:
    """Infer return effects from return expressions."""
    effects: list[ObservedEffect] = []
    for description in facts.return_descriptions:
        effects.append(
            ObservedEffect(
                action="return",
                resource_kind="value",
                target=_stable_short_hash(description),
                output_kind=description,
                confidence="medium",
                evidence=(f"return {description}",),
            )
        )
    return effects


def _effects_from_raises(facts: _FunctionFacts) -> list[ObservedEffect]:
    """Infer raise effects from raise statements."""
    return [
        ObservedEffect(
            action="raise",
            resource_kind="exception",
            target=raised,
            confidence="high",
            evidence=(f"raise {raised}",),
        )
        for raised in facts.raises
    ]


def _effects_from_mutations(facts: _FunctionFacts) -> list[ObservedEffect]:
    """Infer memory-state effects from assignment targets."""
    effects: list[ObservedEffect] = []
    for mutation in facts.mutations:
        if mutation.startswith("self."):
            effects.append(_effect("update", "memory_state", mutation, evidence=f"assign {mutation}"))
    return effects


def _cache_effects(call_name: str, lower_name: str) -> list[ObservedEffect]:
    """Infer cache effects from a cache-like call name."""
    if lower_name.endswith(".get"):
        return [_effect("read", "cache", call_name, evidence=f"call {call_name}")]
    if lower_name.endswith((".set", ".put", ".add")):
        return [_effect("write", "cache", call_name, evidence=f"call {call_name}")]
    if lower_name.endswith((".delete", ".invalidate", ".clear")):
        return [_effect("delete", "cache", call_name, evidence=f"call {call_name}")]
    return [_effect("access", "cache", call_name, evidence=f"call {call_name}")]


def _container_effects(call_name: str, lower_name: str) -> list[ObservedEffect]:
    """Infer container effects from a container-like call name."""
    if lower_name.endswith(".start"):
        return [_effect("start", "container", call_name, evidence=f"call {call_name}")]
    if lower_name.endswith(".stop"):
        return [_effect("stop", "container", call_name, evidence=f"call {call_name}")]
    if lower_name.endswith(".build"):
        return [_effect("create", "container", call_name, evidence=f"call {call_name}")]
    if lower_name.endswith(".run"):
        return [_effect("execute", "container", call_name, evidence=f"call {call_name}")]
    if lower_name.endswith(".remove"):
        return [_effect("delete", "container", call_name, evidence=f"call {call_name}")]
    return [_effect("access", "container", call_name, evidence=f"call {call_name}")]


def _audio_effects(call_name: str, lower_name: str) -> list[ObservedEffect]:
    """Infer audio and music effects from an audio-like call name."""
    if lower_name.endswith(".write") or lower_name.endswith(".send"):
        return [_effect("play", "audio_stream", call_name, evidence=f"call {call_name}")]
    if lower_name.endswith(".read") or lower_name.endswith(".record"):
        return [_effect("record", "audio_stream", call_name, evidence=f"call {call_name}")]
    if lower_name.endswith(".play"):
        return [_effect("play", "audio_stream", call_name, evidence=f"call {call_name}")]
    if lower_name.endswith(".stop"):
        return [_effect("stop", "audio_stream", call_name, evidence=f"call {call_name}")]
    if "midi" in lower_name:
        return [_effect("send", "midi_event", call_name, evidence=f"call {call_name}")]
    return [_effect("access", "audio_stream", call_name, evidence=f"call {call_name}")]


def _sql_effect_from_strings(call_name: str, facts: _FunctionFacts) -> ObservedEffect:
    """Infer a database effect from SQL strings found in the function."""
    for text in facts.string_constants:
        lower_text = text.lower().strip()
        if lower_text.startswith(("insert ", "update ", "delete ", "select ")):
            return _sql_effect_from_text(text, evidence=f"call {call_name}")
    return _effect("access", "database", call_name, evidence=f"call {call_name}")


def _sql_effect_from_text(sql_text: str, evidence: str) -> ObservedEffect:
    """Infer a database effect from one SQL text value."""
    normalized_text = " ".join(sql_text.lower().strip().split())
    if normalized_text.startswith("insert"):
        return _effect("insert", "database", _sql_target(normalized_text), evidence=evidence)
    if normalized_text.startswith("update"):
        return _effect("update", "database", _sql_target(normalized_text), evidence=evidence)
    if normalized_text.startswith("delete"):
        return _effect("delete", "database", _sql_target(normalized_text), evidence=evidence)
    if normalized_text.startswith("select"):
        return _effect("read", "database", _sql_target(normalized_text), evidence=evidence)
    return _effect("access", "database", None, evidence=evidence)


def _sql_target(sql_text: str) -> str | None:
    """Return a best-effort table name from a simple SQL statement."""
    words = sql_text.replace(",", " ").split()
    for marker in ("into", "from", "update"):
        if marker in words:
            index = words.index(marker)
            if index + 1 < len(words):
                return words[index + 1]
    return None


def _finding_code_from_strings(facts: _FunctionFacts) -> str | None:
    """Return a likely finding code from string constants."""
    for value in facts.string_constants:
        if value.isupper() and "_" in value and len(value) > 4:
            return value
    return "finding"


def _deduplicate_effects(effects: list[ObservedEffect]) -> list[ObservedEffect]:
    """Deduplicate effects while preserving order."""
    seen: set[tuple[str, str, str | None, str | None]] = set()
    deduplicated: list[ObservedEffect] = []
    for effect in effects:
        key = (effect.action, effect.resource_kind, effect.target, effect.output_kind)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(effect)
    return deduplicated


def _effect(action: str, resource_kind: str, target: str | None, evidence: str) -> ObservedEffect:
    """Create a compact observed effect."""
    return ObservedEffect(
        action=action,
        resource_kind=resource_kind,
        target=target,
        confidence="high" if target else "medium",
        evidence=(evidence,),
    )


def _effect_priority(effect: ObservedEffect) -> int:
    """Return a comparison priority for one observed effect."""
    score = 0
    if effect.action in _HIGH_SIGNAL_ACTIONS:
        score += 40
    if effect.resource_kind in _PERSISTENT_OR_EXTERNAL_RESOURCES:
        score += 30
    if effect.target is not None:
        score += 20
    if effect.confidence == "high":
        score += 10
    if effect.action in {"return", "parse", "serialize", "access"}:
        score -= 15
    if effect.action == "create" and effect.resource_kind == "directory":
        score -= 30
    if effect.action == "read":
        score -= 20
    return score


def _is_comparable_effect(effect: ObservedEffect) -> bool:
    """Return whether an effect should participate in outcome comparison."""
    if effect.action in {"access", "parse", "read", "serialize"}:
        return False
    if effect.action == "create" and effect.resource_kind == "directory":
        return False
    if effect.resource_kind in {"memory_state", "terminal", "ui", "value"}:
        return False
    if effect.target is not None and effect.target.startswith("self."):
        return False
    return effect.action in _HIGH_SIGNAL_ACTIONS or effect.resource_kind in _PERSISTENT_OR_EXTERNAL_RESOURCES


def _all_units_are_related_interface_methods(fingerprints: list[OutcomeFingerprint]) -> bool:
    """Return whether a group is probably required interface plumbing."""
    method_names = {_last_symbol_part(item.unit.symbol) for item in fingerprints}
    if len(method_names) != 1:
        return False
    method_name = next(iter(method_names))
    if method_name not in {"affected_files", "validate", "is_empty", "lock_file", "unlock_file"}:
        return False
    parent_names = {_parent_symbol_part(item.unit.symbol) for item in fingerprints}
    return len(parent_names) > 1


def _outcome_evidence(
    group: list[tuple[OutcomeFingerprint, ObservedEffect]],
    effect: ObservedEffect,
    confidence: str,
) -> dict[str, Any]:
    """Build evidence for an outcome finding."""
    shared_calls = sorted(set.intersection(*(set(item[0].calls) for item in group))) if group else []
    effect_labels = [_effect_label(item[1]) for item in group]
    return {
        "confidence": confidence,
        "action": effect.action,
        "resource_kind": effect.resource_kind,
        "target": effect.target,
        "units": [_unit_label(item[0].unit) for item in group],
        "effects": effect_labels,
        "shared_calls": shared_calls[:8],
    }


def _effect_label(effect: ObservedEffect) -> str:
    """Return a compact effect label for reports."""
    target = f" {effect.target}" if effect.target else ""
    return f"{effect.action} {effect.resource_kind}{target}".strip()


def _actions_conflict(left_action: str, right_action: str) -> bool:
    """Return whether two actions are known opposites."""
    return (left_action, right_action) in _OPPOSITE_ACTIONS or (right_action, left_action) in _OPPOSITE_ACTIONS


def _stable_pair_key(left: DiscoveredCodeUnit, right: DiscoveredCodeUnit, target: str) -> str:
    """Return a stable pair key for a conflicting-effect finding."""
    labels = sorted([_unit_label(left), _unit_label(right)])
    return "|".join(labels + [target])


def _unknown_external_calls(calls: Iterable[str]) -> set[str]:
    """Return external-looking calls that no analyzer classified."""
    unknown: set[str] = set()
    known_markers = {
        "append",
        "get",
        "items",
        "join",
        "lower",
        "pop",
        "replace",
        "setdefault",
        "split",
        "strip",
        "upper",
        "values",
    }
    classified_markers = {
        "audio",
        "cache",
        "click",
        "commit",
        "container",
        "docker",
        "dump",
        "execute",
        "fit",
        "gpio",
        "http",
        "json",
        "load",
        "logger",
        "metric",
        "open",
        "predict",
        "read_text",
        "redis",
        "request",
        "run",
        "safe_dump",
        "safe_load",
        "send_keys",
        "serial",
        "subprocess",
        "write_text",
        "yaml",
    }
    for call in calls:
        lower_call = call.lower()
        if call in _BUILTIN_CALLS:
            continue
        if any(lower_call.endswith(f".{marker}") for marker in known_markers):
            continue
        if any(marker in lower_call for marker in classified_markers):
            continue
        if "." not in call:
            continue
        if lower_call.startswith(("self.", "cls.")):
            continue
        unknown.add(call)
    return unknown


def _describe_expression(expression: ast.AST) -> str:
    """Return a stable short expression description."""
    try:
        return ast.unparse(expression)
    except ValueError:
        return type(expression).__name__


def _mutation_target(target: ast.AST) -> str | None:
    """Return a stable mutation target description."""
    if isinstance(target, ast.Attribute):
        try:
            return ast.unparse(target)
        except ValueError:
            return target.attr
    if isinstance(target, ast.Subscript):
        try:
            return ast.unparse(target)
        except ValueError:
            return "subscript"
    return None


def _call_name(node: ast.AST) -> str | None:
    """Return a dotted call name from a call target."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent_name = _call_name(node.value)
        if parent_name is None:
            return node.attr
        return f"{parent_name}.{node.attr}"
    return None


def _unit_label(unit: DiscoveredCodeUnit) -> str:
    """Return a stable label for a discovered code unit."""
    return f"{unit.path}::{unit.symbol}"


def _last_symbol_part(symbol: str) -> str:
    """Return the last part of a dotted symbol."""
    return symbol.split(".")[-1]


def _parent_symbol_part(symbol: str) -> str:
    """Return the parent part of a dotted symbol."""
    parts = symbol.split(".")
    if len(parts) < 2:
        return ""
    return parts[-2]


def _stable_short_hash(value: str) -> str:
    """Return a short hash for long dynamic descriptions."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
