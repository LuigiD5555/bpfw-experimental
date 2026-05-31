"""Calculated duplicate profiles for active responsibility collision checks.

The duplicate profile is calculated evidence, not human authority.  It can be
persisted as cache in ``analysis.duplicate_profile``, but every cache entry is
accepted only when its source fingerprint still matches the current code graph.
"""

import ast
import hashlib
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from bpfw.core.catalog.code_duplicates import CodeDuplicateAnalyzer
from bpfw.core.catalog.code_outcomes import CodeOutcomeAnalyzer, _is_comparable_effect
from bpfw.core.catalog.models import DiscoveredCodeUnit
from bpfw.core.catalog.source_repository import SourceFileRepository
from bpfw.reports.finding import FINDING_SEVERITY_BLOCK, FINDING_SEVERITY_WARNING, Finding

_SOURCE = "bpfw"
_DUPLICATE_ACTIVE_PROFILE = "DUPLICATE_ACTIVE_PROFILE"
_DUPLICATE_PROFILE_REVIEW = "DUPLICATE_PROFILE_REVIEW"
_PURPOSE_DUPLICATE_REASON = "two identical purposes"
_ALLOWED_DUPLICATE_PROFILE_REASON = "allowed duplicate profile"
_FUNCTION_TYPES = {"function", "method", "nested_function"}
_IGNORED_HASH_STRENGTHS = {"", "ignored", "weak", "unknown"}
_PROFILE_VERSION = 2
_ANALYZER_VERSION = "duplicate-profile-v2"
_MAX_CHILD_DEPTH = 3
_GENERIC_TARGETS = {"", "*", "unknown", "value", "result", "data", "item", "items", "self", "cls"}
_GENERIC_RETURN_HASH_PREFIXES = {"none", "true", "false"}
_FILE_METHOD_TARGET_SUFFIXES = (
    ".write_text",
    ".write",
    ".writelines",
    ".read_text",
    ".read",
    ".readlines",
    ".mkdir",
    ".unlink",
    ".remove",
    ".rmtree",
    ".rename",
    ".replace",
)
_STRONG_OUTCOME_ACTIONS = {
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
    "move",
    "play",
    "predict",
    "publish",
    "receive",
    "record",
    "render",
    "send",
    "start",
    "stop",
    "train",
    "transform",
    "update",
    "write",
}


@dataclass(frozen=True)
class CodeUnitKey:
    """Identify one code unit from blueprint or scanner metadata."""

    path: str
    symbol: str
    kind: str

    def as_text(self) -> str:
        """Return a stable text label for this code unit."""
        return f"{self.path}::{self.symbol}::{self.kind}"


@dataclass(frozen=True)
class StructureProfile:
    """Describe deterministic structural evidence for one code unit."""

    normalized_ast_hash: str | None = None
    return_expression_hash: str | None = None
    trivial_wrapper: bool = False
    wrapper_target: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert this structure profile to a YAML-safe dictionary."""
        return {
            "normalized_ast_hash": self.normalized_ast_hash,
            "return_expression_hash": self.return_expression_hash,
            "trivial_wrapper": self.trivial_wrapper,
            "wrapper_target": self.wrapper_target,
        }


@dataclass(frozen=True)
class OutcomeProfile:
    """Describe inferred observable outcome evidence for one code unit."""

    action: str | None = None
    resource: str | None = None
    target: str | None = None
    output: str | None = None
    outcome_key: str | None = None
    evidence: tuple[str, ...] = field(default_factory=tuple)
    calls: tuple[str, ...] = field(default_factory=tuple)
    raises: tuple[str, ...] = field(default_factory=tuple)
    mutations: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Convert this outcome profile to a YAML-safe dictionary."""
        return {
            "action": self.action,
            "resource": self.resource,
            "target": self.target,
            "output": self.output,
            "outcome_key": self.outcome_key,
            "evidence": list(self.evidence),
            "calls": list(self.calls),
            "raises": list(self.raises),
            "mutations": list(self.mutations),
        }


@dataclass(frozen=True)
class InterfaceProfile:
    """Describe callable interface evidence for one code unit."""

    inputs: tuple[str, ...] = field(default_factory=tuple)
    output: str | None = None
    interface_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert this interface profile to a YAML-safe dictionary."""
        return {
            "inputs": list(self.inputs),
            "output": self.output,
            "interface_hash": self.interface_hash,
        }


@dataclass(frozen=True)
class SourceFingerprint:
    """Describe the code and dependency state that makes a cached profile valid."""

    analyzer_version: str
    local_hash: str
    dependency_hash: str

    def to_dict(self) -> dict[str, Any]:
        """Convert this source fingerprint to a YAML-safe dictionary."""
        return {
            "analyzer_version": self.analyzer_version,
            "local_hash": self.local_hash,
            "dependency_hash": self.dependency_hash,
        }


@dataclass(frozen=True)
class LocalEvidence:
    """Store local identity evidence for one code unit."""

    path: str
    symbol: str
    kind: str
    decorators: tuple[str, ...] = field(default_factory=tuple)
    constants: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Convert this local evidence to a YAML-safe dictionary."""
        return {
            "path": self.path,
            "symbol": self.symbol,
            "kind": self.kind,
            "decorators": list(self.decorators),
            "constants": list(self.constants),
        }


@dataclass(frozen=True)
class ImportEvidence:
    """Store imports actually used by one code unit."""

    used: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Convert this import evidence to a YAML-safe dictionary."""
        return {"used": list(self.used)}


@dataclass(frozen=True)
class CallGraphEvidence:
    """Store direct and resolved internal call evidence for one code unit."""

    direct: tuple[str, ...] = field(default_factory=tuple)
    resolved_internal: tuple[str, ...] = field(default_factory=tuple)
    unresolved: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Convert this call graph evidence to a YAML-safe dictionary."""
        return {
            "direct": list(self.direct),
            "resolved_internal": list(self.resolved_internal),
            "unresolved": list(self.unresolved),
        }


@dataclass(frozen=True)
class AttributeEvidence:
    """Store attribute read/write and provenance evidence for one code unit."""

    reads: tuple[str, ...] = field(default_factory=tuple)
    writes: tuple[str, ...] = field(default_factory=tuple)
    provenance: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Convert this attribute evidence to a YAML-safe dictionary."""
        return {
            "reads": list(self.reads),
            "writes": list(self.writes),
            "provenance": list(self.provenance),
        }


@dataclass(frozen=True)
class DomainSignal:
    """Describe one domain-specific duplicate signal."""

    action: str
    resource: str
    target: str
    confidence: str
    evidence: str

    def key(self) -> str:
        """Return the stable comparison key for this domain signal."""
        return "|".join([self.action, self.resource, self.target])

    def to_dict(self) -> dict[str, str]:
        """Convert this domain signal to a YAML-safe dictionary."""
        return {
            "action": self.action,
            "resource": self.resource,
            "target": self.target,
            "confidence": self.confidence,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class DomainEvidence:
    """Store detected domain signals for one code unit."""

    detected: tuple[str, ...] = field(default_factory=tuple)
    signals: tuple[DomainSignal, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Convert this domain evidence to a YAML-safe dictionary."""
        return {
            "detected": list(self.detected),
            "signals": [signal.to_dict() for signal in self.signals],
        }


@dataclass(frozen=True)
class ChildProfileEvidence:
    """Store inherited duplicate evidence from resolved child calls."""

    inherited_keys: tuple[str, ...] = field(default_factory=tuple)
    inherited_hashes: tuple[str, ...] = field(default_factory=tuple)
    inherited_strengths: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Convert this child evidence to a YAML-safe dictionary."""
        return {
            "inherited_keys": list(self.inherited_keys),
            "inherited_hashes": list(self.inherited_hashes),
            "inherited_strengths": list(self.inherited_strengths),
        }


@dataclass(frozen=True)
class DuplicateEvidenceBundle:
    """Store all duplicate evidence collected for one code unit."""

    local: LocalEvidence
    structure: StructureProfile
    outcome: OutcomeProfile
    interface: InterfaceProfile
    imports: ImportEvidence
    calls: CallGraphEvidence
    attributes: AttributeEvidence
    domain: DomainEvidence
    children: ChildProfileEvidence
    source_fingerprint: SourceFingerprint


@dataclass(frozen=True)
class DuplicateProfileKeys:
    """Store stable keys used to compare duplicate profiles."""

    duplicate_key: str | None = None
    duplicate_hash: str | None = None
    hash_strength: str = "ignored"
    reason: str | None = None
    duplicated: str = "no"
    group_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert this key profile to a YAML-safe dictionary."""
        return {
            "duplicate_key": self.duplicate_key,
            "duplicate_hash": self.duplicate_hash,
            "hash_strength": self.hash_strength,
            "reason": self.reason,
            "duplicated": self.duplicated,
            "group_size": self.group_size,
        }


@dataclass(frozen=True)
class DuplicateProfile:
    """Store all duplicate-analysis evidence for one code unit."""

    version: int
    confidence: str
    structure: StructureProfile
    outcome: OutcomeProfile
    interface: InterfaceProfile
    keys: DuplicateProfileKeys
    source_fingerprint: SourceFingerprint | None = None
    local: LocalEvidence | None = None
    imports: ImportEvidence = field(default_factory=ImportEvidence)
    calls: CallGraphEvidence = field(default_factory=CallGraphEvidence)
    attributes: AttributeEvidence = field(default_factory=AttributeEvidence)
    domain: DomainEvidence = field(default_factory=DomainEvidence)
    children: ChildProfileEvidence = field(default_factory=ChildProfileEvidence)

    def to_dict(self) -> dict[str, Any]:
        """Convert this duplicate profile to a YAML-safe dictionary."""
        data: dict[str, Any] = {
            "version": self.version,
            "confidence": self.confidence,
            "structure": self.structure.to_dict(),
            "outcome": self.outcome.to_dict(),
            "interface": self.interface.to_dict(),
            "keys": self.keys.to_dict(),
            "imports": self.imports.to_dict(),
            "calls": self.calls.to_dict(),
            "attributes": self.attributes.to_dict(),
            "children": self.children.to_dict(),
            "domain": self.domain.to_dict(),
        }
        if self.local is not None:
            data["local"] = self.local.to_dict()
        if self.source_fingerprint is not None:
            data["source_fingerprint"] = self.source_fingerprint.to_dict()
        return data


class DomainSignalDetector(Protocol):
    """Protocol for domain-specific duplicate signal detectors."""

    def detect(self, evidence: DuplicateEvidenceBundle) -> tuple[DomainSignal, ...]:
        """Return domain signals inferred from the collected evidence."""


class DuplicateProfileBuilder:
    """Build calculated duplicate profiles from discovered Python code units."""

    def __init__(
        self,
        project_root: Path,
        discovered_units: list[DiscoveredCodeUnit],
        source_repository: SourceFileRepository | None = None,
        blocks: list[dict[str, Any]] | None = None,
    ) -> None:
        """Initialize the duplicate-profile builder.

        Args:
            project_root: Project root containing the source files.
            discovered_units: Code units discovered by the scanner.
            source_repository: Optional shared source repository for AST reuse.
            blocks: Optional blueprint blocks used to read cached profiles and
                enrich profiles with duplicate yes/check/no group state.
        """
        self.project_root = project_root
        self.discovered_units = discovered_units
        self.source_repository = source_repository or SourceFileRepository(project_root)
        self.blocks = blocks or []
        self._units_by_key = {code_unit_key_from_discovered_unit(unit): unit for unit in discovered_units}
        self._keys_by_text = {key.as_text(): key for key in self._units_by_key}
        self._block_cache = DuplicateProfileCacheReader(self.blocks).read()
        self._structure_profiles: dict[CodeUnitKey, StructureProfile] = {}
        self._outcome_profiles: dict[CodeUnitKey, OutcomeProfile] = {}
        self._local_bundles: dict[CodeUnitKey, _LocalEvidenceBundle] = {}
        self._resolved_child_keys: dict[CodeUnitKey, tuple[CodeUnitKey, ...]] = {}
        self._profile_cache: dict[CodeUnitKey, DuplicateProfile] = {}
        self._detectors: tuple[DomainSignalDetector, ...] = (
            FilesystemSignalDetector(),
            WebSignalDetector(),
            DatabaseSignalDetector(),
            DataFrameSignalDetector(),
            AutomationSignalDetector(),
            EmbeddedSignalDetector(),
            GameSignalDetector(),
            CliSignalDetector(),
            MessagingSignalDetector(),
            StateMachineSignalDetector(),
        )

    def build(self) -> dict[CodeUnitKey, DuplicateProfile]:
        """Build duplicate profiles keyed by code unit identity.

        Returns:
            Dictionary mapping code unit keys to calculated profiles.
        """
        self._structure_profiles = self._build_structure_profiles()
        self._outcome_profiles = self._build_outcome_profiles()
        self._local_bundles = self._build_local_bundles()
        self._resolved_child_keys = self._build_resolved_child_keys()

        profiles: dict[CodeUnitKey, DuplicateProfile] = {}
        for key in self._units_by_key:
            profiles[key] = self._profile_for_key(key=key, depth=0, seen=frozenset())

        if self.blocks:
            profiles = enrich_duplicate_profile_groups(self.blocks, profiles)
        return profiles

    def _profile_for_key(
        self,
        key: CodeUnitKey,
        depth: int,
        seen: frozenset[CodeUnitKey],
    ) -> DuplicateProfile:
        """Return a profile for one key, recursively resolving child evidence."""
        cached_profile = self._profile_cache.get(key)
        if cached_profile is not None:
            return cached_profile
        if key in seen:
            return self._minimal_cycle_profile(key)

        local_bundle = self._local_bundles.get(key)
        if local_bundle is None:
            profile = self._minimal_cycle_profile(key)
            self._profile_cache[key] = profile
            return profile

        child_profiles: list[DuplicateProfile] = []
        if depth < _MAX_CHILD_DEPTH:
            for child_key in self._resolved_child_keys.get(key, ()):
                child_profiles.append(
                    self._profile_for_key(
                        key=child_key,
                        depth=depth + 1,
                        seen=frozenset(set(seen) | {key}),
                    )
                )

        child_evidence = _child_profile_evidence(child_profiles)
        source_fingerprint = self._build_source_fingerprint(
            key=key,
            local_bundle=local_bundle,
            child_profiles=child_profiles,
        )
        cached_yaml_profile = self._block_cache.get(key)
        if cached_yaml_profile is not None and _cache_profile_is_valid(cached_yaml_profile, source_fingerprint):
            profile = cached_yaml_profile
            self._profile_cache[key] = profile
            return profile

        bundle = DuplicateEvidenceBundle(
            local=local_bundle.local,
            structure=local_bundle.structure,
            outcome=local_bundle.outcome,
            interface=local_bundle.interface,
            imports=local_bundle.imports,
            calls=local_bundle.calls,
            attributes=local_bundle.attributes,
            domain=DomainEvidence(),
            children=child_evidence,
            source_fingerprint=source_fingerprint,
        )
        domain = self._build_domain_evidence(bundle)
        bundle = DuplicateEvidenceBundle(
            local=bundle.local,
            structure=bundle.structure,
            outcome=bundle.outcome,
            interface=bundle.interface,
            imports=bundle.imports,
            calls=bundle.calls,
            attributes=bundle.attributes,
            domain=domain,
            children=bundle.children,
            source_fingerprint=bundle.source_fingerprint,
        )
        keys = CompositeDuplicateKeyBuilder().build(bundle)
        profile = DuplicateProfile(
            version=_PROFILE_VERSION,
            confidence=self._profile_confidence(keys),
            structure=bundle.structure,
            outcome=bundle.outcome,
            interface=bundle.interface,
            keys=keys,
            source_fingerprint=source_fingerprint,
            local=bundle.local,
            imports=bundle.imports,
            calls=bundle.calls,
            attributes=bundle.attributes,
            domain=bundle.domain,
            children=bundle.children,
        )
        self._profile_cache[key] = profile
        return profile

    def _build_structure_profiles(self) -> dict[CodeUnitKey, StructureProfile]:
        """Build structural profile evidence by reusing the code duplicate analyzer."""
        analyzer = CodeDuplicateAnalyzer(
            project_root=self.project_root,
            discovered_units=self.discovered_units,
            source_repository=self.source_repository,
        )
        profiles: dict[CodeUnitKey, StructureProfile] = {}
        for analyzed_unit in analyzer._analyze_units():
            key = code_unit_key_from_discovered_unit(analyzed_unit.unit)
            profiles[key] = StructureProfile(
                normalized_ast_hash=analyzed_unit.body_hash,
                return_expression_hash=analyzed_unit.return_hash,
                trivial_wrapper=analyzed_unit.wrapper_target is not None,
                wrapper_target=analyzed_unit.wrapper_target,
            )
        return profiles

    def _build_outcome_profiles(self) -> dict[CodeUnitKey, OutcomeProfile]:
        """Build outcome profile evidence by reusing the code outcome analyzer."""
        analyzer = CodeOutcomeAnalyzer(
            project_root=self.project_root,
            discovered_units=self.discovered_units,
            source_repository=self.source_repository,
        )
        profiles: dict[CodeUnitKey, OutcomeProfile] = {}
        for fingerprint in analyzer._build_fingerprints():
            primary_effect = fingerprint.primary_effect()
            key = code_unit_key_from_discovered_unit(fingerprint.unit)
            if primary_effect is None:
                profiles[key] = OutcomeProfile(
                    calls=tuple(sorted(fingerprint.calls)),
                    raises=tuple(sorted(fingerprint.raises)),
                    mutations=tuple(sorted(fingerprint.mutations)),
                )
                continue
            profiles[key] = OutcomeProfile(
                action=primary_effect.action,
                resource=primary_effect.resource_kind,
                target=primary_effect.target,
                output=primary_effect.output_kind,
                outcome_key=primary_effect.comparable_key(),
                evidence=primary_effect.evidence,
                calls=tuple(sorted(fingerprint.calls)),
                raises=tuple(sorted(fingerprint.raises)),
                mutations=tuple(sorted(fingerprint.mutations)),
            )
        return profiles

    def _build_local_bundles(self) -> dict[CodeUnitKey, "_LocalEvidenceBundle"]:
        """Build local evidence bundles without recursively resolving children."""
        bundles: dict[CodeUnitKey, _LocalEvidenceBundle] = {}
        local_source_repository = SourceFileRepository(self.project_root)
        import_resolver = UsedImportResolver(local_source_repository)
        attribute_analyzer = AttributeProvenanceAnalyzer(local_source_repository, self.discovered_units)
        for unit in self.discovered_units:
            key = code_unit_key_from_discovered_unit(unit)
            indexed_node = local_source_repository.get_indexed_node(unit.path, unit.symbol)
            constants: tuple[str, ...] = ()
            if indexed_node is not None:
                constants = tuple(sorted(_important_string_constants(indexed_node.node)))
            local = LocalEvidence(
                path=unit.path,
                symbol=unit.symbol,
                kind=unit.symbol_type,
                decorators=tuple(sorted(unit.decorators)),
                constants=constants,
            )
            structure = self._structure_profiles.get(key, StructureProfile())
            outcome = self._outcome_profiles.get(key, OutcomeProfile())
            interface = self._build_interface_profile(unit)
            imports = import_resolver.resolve(unit)
            calls = self._build_call_graph_evidence(unit)
            attributes = attribute_analyzer.analyze(unit)
            bundles[key] = _LocalEvidenceBundle(
                local=local,
                structure=structure,
                outcome=outcome,
                interface=interface,
                imports=imports,
                calls=calls,
                attributes=attributes,
            )
        return bundles

    def _build_call_graph_evidence(self, unit: DiscoveredCodeUnit) -> CallGraphEvidence:
        """Build direct call evidence for one unit before child resolution."""
        direct_calls = tuple(sorted(_call_texts_from_unit(unit)))
        return CallGraphEvidence(direct=direct_calls)

    def _build_resolved_child_keys(self) -> dict[CodeUnitKey, tuple[CodeUnitKey, ...]]:
        """Resolve internal calls to discovered code unit keys."""
        resolver = InternalCallGraphBuilder(self.discovered_units)
        resolved: dict[CodeUnitKey, tuple[CodeUnitKey, ...]] = {}
        for unit in self.discovered_units:
            key = code_unit_key_from_discovered_unit(unit)
            resolved[key] = resolver.resolve(unit)
            existing_bundle = self._local_bundles.get(key)
            if existing_bundle is not None:
                resolved_labels = tuple(child_key.as_text() for child_key in resolved[key])
                direct_calls = tuple(sorted(_call_texts_from_unit(unit)))
                unresolved = tuple(sorted(set(direct_calls) - {_short_call_from_key(child_key) for child_key in resolved[key]}))
                self._local_bundles[key] = _LocalEvidenceBundle(
                    local=existing_bundle.local,
                    structure=existing_bundle.structure,
                    outcome=existing_bundle.outcome,
                    interface=existing_bundle.interface,
                    imports=existing_bundle.imports,
                    calls=CallGraphEvidence(
                        direct=direct_calls,
                        resolved_internal=resolved_labels,
                        unresolved=unresolved,
                    ),
                    attributes=existing_bundle.attributes,
                )
        return resolved

    def _build_interface_profile(self, unit: DiscoveredCodeUnit) -> InterfaceProfile:
        """Build interface evidence from scanner metadata for one unit."""
        input_names: list[str] = []
        for input_data in unit.interface_inputs:
            if not isinstance(input_data, dict):
                continue
            input_name = input_data.get("name")
            input_type = input_data.get("type")
            if isinstance(input_name, str) and input_name:
                if isinstance(input_type, str) and input_type:
                    input_names.append(f"{input_name}:{input_type}")
                else:
                    input_names.append(input_name)

        output_type = None
        if isinstance(unit.interface_output, dict):
            output_value = unit.interface_output.get("type")
            if isinstance(output_value, str) and output_value:
                output_type = output_value

        interface_text = "|".join(input_names + [output_type or "*"])
        interface_hash = _stable_hash(interface_text) if interface_text != "*" else None
        return InterfaceProfile(
            inputs=tuple(input_names),
            output=output_type,
            interface_hash=interface_hash,
        )

    def _build_domain_evidence(self, bundle: DuplicateEvidenceBundle) -> DomainEvidence:
        """Run domain detectors and collect domain-specific signals."""
        signals: list[DomainSignal] = []
        detected: set[str] = set()
        for detector in self._detectors:
            detector_signals = detector.detect(bundle)
            signals.extend(detector_signals)
            for signal in detector_signals:
                detected.add(signal.resource)
        return DomainEvidence(detected=tuple(sorted(detected)), signals=tuple(_deduplicate_signals(signals)))

    def _build_source_fingerprint(
        self,
        key: CodeUnitKey,
        local_bundle: "_LocalEvidenceBundle",
        child_profiles: list[DuplicateProfile],
    ) -> SourceFingerprint:
        """Build an invalidable fingerprint for a calculated profile."""
        unit = self._units_by_key[key]
        local_parts = [
            unit.normalized_body_hash or "",
            _hash_tuple(local_bundle.imports.used),
            _hash_tuple(local_bundle.calls.direct),
            _hash_tuple(local_bundle.local.decorators),
            _hash_tuple(local_bundle.local.constants),
            _hash_tuple(local_bundle.attributes.reads),
            _hash_tuple(local_bundle.attributes.writes),
            _hash_tuple(local_bundle.outcome.mutations),
            _hash_tuple(local_bundle.outcome.raises),
            local_bundle.interface.interface_hash or "",
        ]
        dependency_parts: list[str] = []
        for child_profile in child_profiles:
            if child_profile.source_fingerprint is not None:
                dependency_parts.append(child_profile.source_fingerprint.local_hash)
                dependency_parts.append(child_profile.source_fingerprint.dependency_hash)
            if child_profile.keys.duplicate_hash:
                dependency_parts.append(child_profile.keys.duplicate_hash)
        return SourceFingerprint(
            analyzer_version=_ANALYZER_VERSION,
            local_hash=_stable_hash("|".join(local_parts)) or "",
            dependency_hash=_stable_hash("|".join(sorted(dependency_parts))) or "",
        )

    def _minimal_cycle_profile(self, key: CodeUnitKey) -> DuplicateProfile:
        """Build a safe ignored profile for cycles or missing metadata."""
        return DuplicateProfile(
            version=_PROFILE_VERSION,
            confidence="low",
            structure=StructureProfile(),
            outcome=OutcomeProfile(),
            interface=InterfaceProfile(),
            keys=DuplicateProfileKeys(reason="profile unavailable"),
            local=LocalEvidence(path=key.path, symbol=key.symbol, kind=key.kind),
        )

    def _profile_confidence(self, keys: DuplicateProfileKeys) -> str:
        """Return a compact confidence label for a calculated profile."""
        if keys.hash_strength == "strong":
            return "high"
        if keys.hash_strength == "weak":
            return "medium"
        return "low"


@dataclass(frozen=True)
class _LocalEvidenceBundle:
    """Store local evidence before recursive child profile inheritance."""

    local: LocalEvidence
    structure: StructureProfile
    outcome: OutcomeProfile
    interface: InterfaceProfile
    imports: ImportEvidence
    calls: CallGraphEvidence
    attributes: AttributeEvidence


class DuplicateProfileCacheReader:
    """Read optional duplicate profile cache entries from blueprint blocks."""

    def __init__(self, blocks: list[dict[str, Any]]) -> None:
        """Initialize the cache reader.

        Args:
            blocks: Blueprint blocks that may contain analysis.duplicate_profile.
        """
        self.blocks = blocks

    def read(self) -> dict[CodeUnitKey, DuplicateProfile]:
        """Return valid-looking cached profiles keyed by code unit."""
        profiles: dict[CodeUnitKey, DuplicateProfile] = {}
        for block in self.blocks:
            if not isinstance(block, dict):
                continue
            key = code_unit_key_from_block(block)
            if key is None:
                continue
            analysis = block.get("analysis")
            if not isinstance(analysis, dict):
                continue
            raw_profile = analysis.get("duplicate_profile")
            if not isinstance(raw_profile, dict):
                continue
            profile = _profile_from_cache(raw_profile)
            if profile is not None:
                profiles[key] = profile
        return profiles


class UsedImportResolver:
    """Resolve imports actually referenced inside each code unit."""

    def __init__(self, source_repository: SourceFileRepository) -> None:
        """Initialize the resolver with a shared source repository."""
        self.source_repository = source_repository
        self._aliases_by_path: dict[str, dict[str, str]] = {}

    def resolve(self, unit: DiscoveredCodeUnit) -> ImportEvidence:
        """Return imports used inside the given code unit."""
        indexed_node = self.source_repository.get_indexed_node(unit.path, unit.symbol)
        if indexed_node is None:
            return ImportEvidence()
        aliases = self._aliases_for_path(unit.path)
        used_names = _used_name_roots(indexed_node.node)
        used_imports: set[str] = set()
        for used_name in used_names:
            import_name = aliases.get(used_name)
            if import_name is not None:
                used_imports.add(import_name)
        return ImportEvidence(used=tuple(sorted(used_imports)))

    def _aliases_for_path(self, path: str) -> dict[str, str]:
        """Return import aliases keyed by the local name available in code."""
        cached_aliases = self._aliases_by_path.get(path)
        if cached_aliases is not None:
            return cached_aliases
        snapshot = self.source_repository.get_snapshot(path)
        if snapshot is None:
            self._aliases_by_path[path] = {}
            return {}
        aliases: dict[str, str] = {}
        for node in ast.walk(snapshot.syntax_tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local_name = alias.asname or alias.name.split(".", 1)[0]
                    aliases[local_name] = alias.name
                continue
            if isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    local_name = alias.asname or alias.name
                    full_name = f"{module_name}.{alias.name}" if module_name else alias.name
                    aliases[local_name] = full_name
        self._aliases_by_path[path] = aliases
        return aliases


class InternalCallGraphBuilder:
    """Resolve simple internal calls between discovered code units."""

    def __init__(self, discovered_units: list[DiscoveredCodeUnit]) -> None:
        """Initialize indexes used for internal call resolution."""
        self.units = discovered_units
        self._keys_by_path_symbol: dict[tuple[str, str], CodeUnitKey] = {}
        self._keys_by_path_leaf: dict[tuple[str, str], list[CodeUnitKey]] = {}
        for unit in discovered_units:
            key = code_unit_key_from_discovered_unit(unit)
            self._keys_by_path_symbol[(unit.path, unit.symbol)] = key
            leaf = unit.symbol.rsplit(".", 1)[-1]
            self._keys_by_path_leaf.setdefault((unit.path, leaf), []).append(key)

    def resolve(self, unit: DiscoveredCodeUnit) -> tuple[CodeUnitKey, ...]:
        """Resolve internal calls made by a unit into code unit keys."""
        resolved: list[CodeUnitKey] = []
        seen: set[CodeUnitKey] = set()
        for call in unit.calls:
            if not isinstance(call, dict):
                continue
            child_key = self._resolve_call(unit, call)
            if child_key is None or child_key in seen:
                continue
            seen.add(child_key)
            resolved.append(child_key)
        return tuple(resolved)

    def _resolve_call(self, unit: DiscoveredCodeUnit, call: dict[str, Any]) -> CodeUnitKey | None:
        """Resolve one structured call dictionary into a code unit key."""
        call_name = call.get("name")
        context = call.get("context")
        if not isinstance(call_name, str) or not call_name:
            return None
        if context in {"self", "cls"} and "." in unit.symbol:
            class_symbol = unit.symbol.rsplit(".", 1)[0]
            candidate = self._keys_by_path_symbol.get((unit.path, f"{class_symbol}.{call_name}"))
            if candidate is not None:
                return candidate
        direct_candidates = self._keys_by_path_leaf.get((unit.path, call_name), [])
        if len(direct_candidates) == 1:
            return direct_candidates[0]
        symbol_candidate = self._keys_by_path_symbol.get((unit.path, call_name))
        if symbol_candidate is not None:
            return symbol_candidate
        return None


class AttributeProvenanceAnalyzer:
    """Track simple self.x readers, writers, and source expressions inside classes."""

    def __init__(self, source_repository: SourceFileRepository, discovered_units: list[DiscoveredCodeUnit]) -> None:
        """Initialize the analyzer with source access and discovered units."""
        self.source_repository = source_repository
        self.discovered_units = discovered_units
        self._class_writers: dict[tuple[str, str], dict[str, set[str]]] = {}

    def analyze(self, unit: DiscoveredCodeUnit) -> AttributeEvidence:
        """Return attribute evidence for one unit."""
        indexed_node = self.source_repository.get_indexed_node(unit.path, unit.symbol)
        if indexed_node is None:
            return AttributeEvidence()
        reads = tuple(sorted(_self_attribute_reads(indexed_node.node)))
        writes = tuple(sorted(_self_attribute_writes(indexed_node.node)))
        provenance = tuple(sorted(self._provenance_for_reads(unit, reads)))
        return AttributeEvidence(reads=reads, writes=writes, provenance=provenance)

    def _provenance_for_reads(self, unit: DiscoveredCodeUnit, reads: tuple[str, ...]) -> set[str]:
        """Return source provenance entries for the given self attribute reads."""
        if "." not in unit.symbol:
            return set()
        class_symbol = unit.symbol.rsplit(".", 1)[0]
        writers = self._writers_for_class(path=unit.path, class_symbol=class_symbol)
        provenance: set[str] = set()
        for read_name in reads:
            for source in writers.get(read_name, set()):
                provenance.add(f"{read_name}<-{source}")
        return provenance

    def _writers_for_class(self, path: str, class_symbol: str) -> dict[str, set[str]]:
        """Return writer source expressions for a class symbol."""
        cache_key = (path, class_symbol)
        cached_writers = self._class_writers.get(cache_key)
        if cached_writers is not None:
            return cached_writers
        indexed_node = self.source_repository.get_indexed_node(path, class_symbol)
        if indexed_node is None or not isinstance(indexed_node.node, ast.ClassDef):
            self._class_writers[cache_key] = {}
            return {}
        writers: dict[str, set[str]] = {}
        for child in indexed_node.node.body:
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(child):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        attribute_name = _self_attribute_name(target)
                        if attribute_name is not None:
                            writers.setdefault(attribute_name, set()).add(_safe_unparse(node.value))
                elif isinstance(node, ast.AnnAssign):
                    attribute_name = _self_attribute_name(node.target)
                    if attribute_name is not None and node.value is not None:
                        writers.setdefault(attribute_name, set()).add(_safe_unparse(node.value))
                elif isinstance(node, ast.AugAssign):
                    attribute_name = _self_attribute_name(node.target)
                    if attribute_name is not None:
                        writers.setdefault(attribute_name, set()).add(_safe_unparse(node.value))
        self._class_writers[cache_key] = writers
        return writers


class CompositeDuplicateKeyBuilder:
    """Build duplicate keys from complete connected duplicate evidence."""

    def build(self, evidence: DuplicateEvidenceBundle) -> DuplicateProfileKeys:
        """Return the duplicate key and strength for one evidence bundle."""
        hard_signal = self._hard_signal(evidence)
        if hard_signal is not None:
            duplicate_key = hard_signal.key()
            return DuplicateProfileKeys(
                duplicate_key=duplicate_key,
                duplicate_hash=_stable_hash(duplicate_key),
                hash_strength="strong",
                reason=f"hard signal: {hard_signal.evidence}",
            )

        child_key = self._child_signal(evidence)
        if child_key is not None:
            return child_key

        composite_key = self._composite_medium_signal(evidence)
        if composite_key is not None:
            return composite_key

        if evidence.structure.return_expression_hash is not None and not self._generic_return(evidence):
            duplicate_key = f"return|{evidence.structure.return_expression_hash}"
            return DuplicateProfileKeys(
                duplicate_key=duplicate_key,
                duplicate_hash=_stable_hash(duplicate_key),
                hash_strength="weak",
                reason="same non-generic return expression",
            )

        if evidence.structure.normalized_ast_hash is not None:
            duplicate_key = f"structure|{evidence.structure.normalized_ast_hash}"
            return DuplicateProfileKeys(
                duplicate_key=duplicate_key,
                duplicate_hash=_stable_hash(duplicate_key),
                hash_strength="weak",
                reason="same normalized structure",
            )

        return DuplicateProfileKeys(reason="no useful duplicate signal")

    def _hard_signal(self, evidence: DuplicateEvidenceBundle) -> DomainSignal | None:
        """Return the first strong direct signal for the evidence bundle."""
        if evidence.local.kind not in _FUNCTION_TYPES:
            return None
        for signal in evidence.domain.signals:
            if signal.confidence != "high" or _is_generic_target(signal.target):
                continue
            if signal.action in {"return", "access", "parse", "serialize", "read"}:
                continue
            return signal
        if _is_strong_outcome(evidence.outcome):
            target = evidence.outcome.target or "*"
            action = evidence.outcome.action or "unknown"
            resource = evidence.outcome.resource or "unknown"
            output = evidence.outcome.output or "*"
            return DomainSignal(
                action=action,
                resource=resource,
                target=f"{target}|{output}",
                confidence="high",
                evidence="direct observable outcome",
            )
        if evidence.structure.trivial_wrapper and evidence.structure.wrapper_target and not evidence.children.inherited_keys:
            return DomainSignal(
                action="wrapper",
                resource="call",
                target=evidence.structure.wrapper_target,
                confidence="high",
                evidence="trivial wrapper target",
            )
        return None

    def _child_signal(self, evidence: DuplicateEvidenceBundle) -> DuplicateProfileKeys | None:
        """Return inherited child duplicate signal when child evidence is useful."""
        strong_child_keys = [
            key
            for key, strength in zip(evidence.children.inherited_keys, evidence.children.inherited_strengths)
            if strength == "strong"
        ]
        if not strong_child_keys:
            return None
        child_key = strong_child_keys[0]
        if evidence.structure.trivial_wrapper or (
            evidence.outcome.action == "return"
            and len(evidence.calls.resolved_internal) == 1
            and len(evidence.calls.direct) <= 1
        ):
            delegate_target = evidence.structure.wrapper_target or evidence.calls.direct[0] if evidence.calls.direct else "child"
            duplicate_key = f"delegate|{delegate_target}|child:{child_key}"
            return DuplicateProfileKeys(
                duplicate_key=duplicate_key,
                duplicate_hash=_stable_hash(duplicate_key),
                hash_strength="strong",
                reason="delegating wrapper inherits strong child profile",
            )
        if evidence.interface.interface_hash and len(evidence.calls.resolved_internal) == 1:
            duplicate_key = f"child|{child_key}|interface:{evidence.interface.interface_hash}"
            return DuplicateProfileKeys(
                duplicate_key=duplicate_key,
                duplicate_hash=_stable_hash(duplicate_key),
                hash_strength="weak",
                reason="same child profile through a non-wrapper boundary",
            )
        duplicate_key = f"child|{child_key}"
        return DuplicateProfileKeys(
            duplicate_key=duplicate_key,
            duplicate_hash=_stable_hash(duplicate_key),
            hash_strength="weak",
            reason="inherits child profile but parent boundary is not trivial",
        )

    def _composite_medium_signal(self, evidence: DuplicateEvidenceBundle) -> DuplicateProfileKeys | None:
        """Return a strong composite key when medium signals agree."""
        if evidence.local.kind not in _FUNCTION_TYPES:
            return None
        parts: list[str] = []
        if evidence.calls.resolved_internal:
            parts.append(f"calls:{','.join(evidence.calls.resolved_internal[:3])}")
        if evidence.imports.used:
            parts.append(f"imports:{','.join(evidence.imports.used[:4])}")
        if evidence.interface.interface_hash:
            parts.append(f"interface:{evidence.interface.interface_hash}")
        if evidence.local.constants:
            parts.append(f"constants:{','.join(evidence.local.constants[:3])}")
        if evidence.attributes.provenance:
            parts.append(f"attrs:{','.join(evidence.attributes.provenance[:3])}")
        if evidence.outcome.mutations:
            parts.append(f"mutations:{','.join(evidence.outcome.mutations[:3])}")
        if len(parts) < 3:
            return None
        has_context_anchor = bool(evidence.calls.resolved_internal or evidence.domain.signals or evidence.attributes.provenance)
        if not has_context_anchor:
            return None
        duplicate_key = "composite|" + "|".join(parts)
        return DuplicateProfileKeys(
            duplicate_key=duplicate_key,
            duplicate_hash=_stable_hash(duplicate_key),
            hash_strength="weak",
            reason="multiple compatible medium signals",
        )

    def _generic_return(self, evidence: DuplicateEvidenceBundle) -> bool:
        """Return whether return evidence is too generic to use."""
        if evidence.attributes.reads and not evidence.attributes.provenance:
            return True
        return_hash = evidence.structure.return_expression_hash or ""
        return any(return_hash.startswith(prefix) for prefix in _GENERIC_RETURN_HASH_PREFIXES)


class FilesystemSignalDetector:
    """Detect filesystem-oriented duplicate signals."""

    def detect(self, evidence: DuplicateEvidenceBundle) -> tuple[DomainSignal, ...]:
        """Return filesystem signals inferred from calls and constants."""
        signals: list[DomainSignal] = []
        for constant in evidence.local.constants:
            if _looks_like_path(constant):
                action = evidence.outcome.action or "access"
                confidence = "high" if action in _STRONG_OUTCOME_ACTIONS else "medium"
                signals.append(DomainSignal(action, "file", constant, confidence, f"path constant {constant}"))
        return tuple(signals)


class WebSignalDetector:
    """Detect web route duplicate signals."""

    def detect(self, evidence: DuplicateEvidenceBundle) -> tuple[DomainSignal, ...]:
        """Return web route signals inferred from decorators and constants."""
        signals: list[DomainSignal] = []
        for decorator in evidence.local.decorators:
            route_signal = _route_signal_from_decorator(decorator, evidence.local.constants)
            if route_signal is not None:
                signals.append(route_signal)
        for constant in evidence.local.constants:
            if constant.startswith("/") and len(constant) > 1:
                signals.append(DomainSignal("route", "http_endpoint", constant, "medium", f"endpoint constant {constant}"))
        return tuple(signals)


class DatabaseSignalDetector:
    """Detect database duplicate signals."""

    def detect(self, evidence: DuplicateEvidenceBundle) -> tuple[DomainSignal, ...]:
        """Return database signals inferred from imports, calls, and SQL strings."""
        signals: list[DomainSignal] = []
        used_imports = "|".join(evidence.imports.used).lower()
        if any(marker in used_imports for marker in ("sqlalchemy", "sqlite", "psycopg", "django.db")):
            target = _first_sql_target(evidence.local.constants) or evidence.outcome.target or "database"
            action = evidence.outcome.action or "query"
            signals.append(DomainSignal(action, "database", target, "high", "database import/call"))
        sql_target = _first_sql_target(evidence.local.constants)
        if sql_target is not None:
            signals.append(DomainSignal("execute", "database", sql_target, "high", "SQL constant"))
        return tuple(signals)


class DataFrameSignalDetector:
    """Detect dataframe duplicate signals."""

    def detect(self, evidence: DuplicateEvidenceBundle) -> tuple[DomainSignal, ...]:
        """Return dataframe signals inferred from imports and mutations."""
        if not any(import_name.startswith("pandas") for import_name in evidence.imports.used):
            return ()
        signals: list[DomainSignal] = []
        for mutation in evidence.outcome.mutations:
            column = _dataframe_column_from_mutation(mutation)
            if column is not None:
                signals.append(DomainSignal("mutate", "dataframe_column", column, "high", f"dataframe mutation {mutation}"))
        return tuple(signals)


class AutomationSignalDetector:
    """Detect process and automation duplicate signals."""

    def detect(self, evidence: DuplicateEvidenceBundle) -> tuple[DomainSignal, ...]:
        """Return automation signals inferred from calls and constants."""
        signals: list[DomainSignal] = []
        calls = "|".join(evidence.calls.direct).lower()
        if "subprocess" in calls or any(import_name == "subprocess" for import_name in evidence.imports.used):
            target = _first_command_constant(evidence.local.constants) or "process"
            signals.append(DomainSignal("execute", "process", target, "high", "subprocess call"))
        return tuple(signals)


class EmbeddedSignalDetector:
    """Detect embedded hardware duplicate signals."""

    def detect(self, evidence: DuplicateEvidenceBundle) -> tuple[DomainSignal, ...]:
        """Return embedded device signals inferred from imports and constants."""
        imports_text = "|".join(evidence.imports.used).lower()
        if not any(marker in imports_text for marker in ("gpio", "serial", "smbus", "machine")):
            return ()
        target = _first_gpio_constant(evidence.local.constants) or "device"
        return (DomainSignal("write", "gpio_pin", target, "high", "embedded import/constant"),)


class GameSignalDetector:
    """Detect game state duplicate signals."""

    def detect(self, evidence: DuplicateEvidenceBundle) -> tuple[DomainSignal, ...]:
        """Return game-oriented state mutation signals."""
        imports_text = "|".join(evidence.imports.used).lower()
        if not any(marker in imports_text for marker in ("pygame", "arcade", "pyglet")):
            return ()
        signals: list[DomainSignal] = []
        for mutation in evidence.outcome.mutations:
            if any(marker in mutation.lower() for marker in ("position", "rect", "health", "velocity", "score")):
                signals.append(DomainSignal("mutate", "game_entity", mutation, "high", f"game mutation {mutation}"))
        return tuple(signals)


class CliSignalDetector:
    """Detect CLI command duplicate signals."""

    def detect(self, evidence: DuplicateEvidenceBundle) -> tuple[DomainSignal, ...]:
        """Return CLI signals inferred from decorators and imports."""
        decorators = "|".join(evidence.local.decorators).lower()
        imports_text = "|".join(evidence.imports.used).lower()
        if "click" in imports_text or "typer" in imports_text or "command" in decorators:
            target = evidence.local.symbol.rsplit(".", 1)[-1]
            return (DomainSignal("command", "cli", target, "high", "CLI decorator/import"),)
        return ()


class MessagingSignalDetector:
    """Detect message queue or event duplicate signals."""

    def detect(self, evidence: DuplicateEvidenceBundle) -> tuple[DomainSignal, ...]:
        """Return messaging signals inferred from calls and constants."""
        calls = "|".join(evidence.calls.direct).lower()
        if not any(marker in calls for marker in ("publish", "send", "emit", "enqueue")):
            return ()
        event_name = _first_event_constant(evidence.local.constants) or "message"
        return (DomainSignal("publish", "message_queue", event_name, "high", "publish/send/emit call"),)


class StateMachineSignalDetector:
    """Detect internal state duplicate signals."""

    def detect(self, evidence: DuplicateEvidenceBundle) -> tuple[DomainSignal, ...]:
        """Return state signals inferred from attributes and provenance."""
        signals: list[DomainSignal] = []
        for provenance in evidence.attributes.provenance:
            if "<-" in provenance:
                attribute, source = provenance.split("<-", 1)
                if source and source not in _GENERIC_TARGETS:
                    signals.append(DomainSignal("read_state", "object_attribute", f"{attribute}|source:{source}", "medium", "attribute provenance"))
        for write in evidence.attributes.writes:
            if any(marker in write.lower() for marker in ("status", "state", "ready", "enabled", "current")):
                signals.append(DomainSignal("mutate", "object_state", write, "medium", "state-like attribute write"))
        return tuple(signals)


@dataclass(frozen=True)
class _EffectProxy:
    """Adapt profile data to the small interface expected by outcome helpers."""

    action: str
    resource_kind: str
    target: str | None
    output_kind: str | None


def _is_strong_outcome(outcome: OutcomeProfile) -> bool:
    """Return whether an outcome profile is strong enough to block active duplicates."""
    if not outcome.action or not outcome.resource or not outcome.outcome_key:
        return False
    if outcome.action not in _STRONG_OUTCOME_ACTIONS:
        return False
    if outcome.resource == "database" and outcome.target and " " in outcome.target and not _looks_like_sql(outcome.target):
        return False
    if outcome.resource in {"file", "directory"} and _is_variable_file_method_target(outcome.target):
        return False
    effect_proxy = _EffectProxy(
        action=outcome.action,
        resource_kind=outcome.resource,
        target=outcome.target,
        output_kind=outcome.output,
    )
    if not _is_comparable_effect(effect_proxy):
        return False
    if outcome.target is None:
        return outcome.action in {"execute", "render", "train", "predict"}
    if _is_generic_target(outcome.target):
        return False
    return True


class DuplicateActiveProfileRule:
    """Detect active blocks sharing the same strong calculated duplicate hash."""

    def validate(
        self,
        blocks: list[Any],
        profiles_by_key: dict[CodeUnitKey, DuplicateProfile],
    ) -> list[Finding]:
        """Return blocking findings for active duplicate declarations or profiles.

        Args:
            blocks: Raw blueprint blocks.
            profiles_by_key: Profiles calculated from discovered code.

        Returns:
            Blocking findings for strong active duplicate profile collisions and
            identical active purposes declared by the user.
        """
        raw_blocks = [block for block in blocks if isinstance(block, dict)]
        enriched_profiles = enrich_duplicate_profile_groups(raw_blocks, profiles_by_key)
        purpose_groups = _active_purpose_duplicate_groups(raw_blocks)
        purpose_group_id_sets = {
            frozenset(_block_id(block) for block in group if _block_id(block))
            for group in purpose_groups.values()
        }

        groups: dict[tuple[str, str], list[tuple[dict[str, Any], DuplicateProfile]]] = {}
        for block in raw_blocks:
            if block.get("status") != "active":
                continue
            key = code_unit_key_from_block(block)
            if key is None:
                continue
            profile = enriched_profiles.get(key)
            if profile is None:
                continue
            if profile.keys.reason == _PURPOSE_DUPLICATE_REASON:
                continue
            if profile.keys.hash_strength in {"", "ignored", "unknown"}:
                continue
            if not profile.keys.duplicate_hash:
                continue
            group_key = (profile.keys.duplicate_hash, profile.keys.hash_strength)
            groups.setdefault(group_key, []).append((block, profile))

        findings: list[Finding] = []
        for group_key, group in groups.items():
            duplicate_hash, hash_strength = group_key
            if len(group) < 2:
                continue
            if _all_blocks_are_parallel_strategy_methods(group):
                continue
            first_block, first_profile = group[0]
            if _duplicate_profile_group_is_allowed(
                group_blocks=[block for block, _profile in group],
                duplicate_hash=duplicate_hash,
                duplicate_key=first_profile.keys.duplicate_key,
            ):
                continue
            active_ids = frozenset(_block_id(block) for block, _profile in group if _block_id(block))
            if active_ids in purpose_group_id_sets:
                continue
            active_blocks = [_active_block_evidence(block) for block, _profile in group]
            if hash_strength == "strong":
                findings.append(
                    _duplicate_profile_finding(
                        first_block=first_block,
                        duplicate_hash=duplicate_hash,
                        duplicate_key=first_profile.keys.duplicate_key,
                        hash_strength=first_profile.keys.hash_strength,
                        reason=first_profile.keys.reason,
                        active_blocks=active_blocks,
                    )
                )
            elif hash_strength == "weak":
                findings.append(
                    _duplicate_profile_review_finding(
                        first_block=first_block,
                        duplicate_hash=duplicate_hash,
                        duplicate_key=first_profile.keys.duplicate_key,
                        hash_strength=first_profile.keys.hash_strength,
                        reason=first_profile.keys.reason,
                        active_blocks=active_blocks,
                    )
                )

        for normalized_purpose, group_blocks in purpose_groups.items():
            first_block = group_blocks[0]
            duplicate_key = _purpose_duplicate_key(normalized_purpose)
            duplicate_hash = _stable_hash(duplicate_key)
            if _duplicate_profile_group_is_allowed(
                group_blocks=group_blocks,
                duplicate_hash=duplicate_hash,
                duplicate_key=duplicate_key,
            ):
                continue
            findings.append(
                _duplicate_profile_finding(
                    first_block=first_block,
                    duplicate_hash=duplicate_hash,
                    duplicate_key=duplicate_key,
                    hash_strength="strong",
                    reason=_PURPOSE_DUPLICATE_REASON,
                    active_blocks=[_active_block_evidence(block) for block in group_blocks],
                )
            )
        return findings


def enrich_duplicate_profile_groups(
    blocks: list[dict[str, Any]],
    profiles_by_key: dict[CodeUnitKey, DuplicateProfile],
) -> dict[CodeUnitKey, DuplicateProfile]:
    """Return profiles enriched with duplicated yes/check/no group status."""
    group_counts: dict[tuple[str, str], int] = {}
    group_blocks: dict[tuple[str, str], list[dict[str, Any]]] = {}
    active_keys: list[CodeUnitKey] = []
    for block in blocks:
        if block.get("status") != "active":
            continue
        key = code_unit_key_from_block(block)
        if key is None:
            continue
        profile = profiles_by_key.get(key)
        if profile is None:
            continue
        active_keys.append(key)
        if not profile.keys.duplicate_hash:
            continue
        group_key = (profile.keys.duplicate_hash, profile.keys.hash_strength)
        group_counts[group_key] = group_counts.get(group_key, 0) + 1
        group_blocks.setdefault(group_key, []).append(block)

    purpose_groups = _active_purpose_duplicate_groups(blocks)
    purpose_group_by_key: dict[CodeUnitKey, tuple[str, int]] = {}
    for normalized_purpose, group_blocks in purpose_groups.items():
        group_size = len(group_blocks)
        for block in group_blocks:
            key = code_unit_key_from_block(block)
            if key is not None:
                purpose_group_by_key[key] = (normalized_purpose, group_size)

    enriched: dict[CodeUnitKey, DuplicateProfile] = dict(profiles_by_key)
    for key in active_keys:
        profile = profiles_by_key.get(key)
        if profile is None:
            continue
        purpose_group = purpose_group_by_key.get(key)
        if purpose_group is not None:
            normalized_purpose, purpose_group_size = purpose_group
            duplicate_key = _purpose_duplicate_key(normalized_purpose)
            duplicate_hash = _stable_hash(duplicate_key)
            purpose_group_blocks = purpose_groups.get(normalized_purpose, [])
            allowed = _duplicate_profile_group_is_allowed(
                group_blocks=purpose_group_blocks,
                duplicate_hash=duplicate_hash,
                duplicate_key=duplicate_key,
            )
            enriched[key] = replace(
                profile,
                keys=replace(
                    profile.keys,
                    duplicate_key=duplicate_key,
                    duplicate_hash=duplicate_hash,
                    hash_strength="strong",
                    reason=_ALLOWED_DUPLICATE_PROFILE_REASON if allowed else _PURPOSE_DUPLICATE_REASON,
                    duplicated="no" if allowed else "yes",
                    group_size=purpose_group_size,
                ),
            )
            continue

        if not profile.keys.duplicate_hash:
            continue
        group_key = (profile.keys.duplicate_hash, profile.keys.hash_strength)
        group_size = group_counts.get(group_key, 0)
        duplicated = "no"
        reason = profile.keys.reason
        if group_size > 1 and _duplicate_profile_group_is_allowed(
            group_blocks=group_blocks.get(group_key, []),
            duplicate_hash=profile.keys.duplicate_hash,
            duplicate_key=profile.keys.duplicate_key,
        ):
            duplicated = "no"
            reason = _ALLOWED_DUPLICATE_PROFILE_REASON
        elif group_size > 1 and profile.keys.hash_strength == "strong":
            duplicated = "yes"
        elif group_size > 1 and profile.keys.hash_strength == "weak":
            duplicated = "check"
        enriched[key] = replace(
            profile,
            keys=replace(profile.keys, duplicated=duplicated, group_size=group_size, reason=reason),
        )
    return enriched


def code_unit_key_from_discovered_unit(unit: DiscoveredCodeUnit) -> CodeUnitKey:
    """Build a code unit key from one discovered unit."""
    return CodeUnitKey(path=unit.path, symbol=unit.symbol, kind=unit.symbol_type)


def code_unit_key_from_block(block: dict[str, Any]) -> CodeUnitKey | None:
    """Build a code unit key from one blueprint block when possible."""
    code = block.get("code")
    if not isinstance(code, dict):
        return None
    path = code.get("path")
    symbol = code.get("symbol")
    kind = code.get("kind")
    if not isinstance(path, str) or not path:
        return None
    if not isinstance(symbol, str) or not symbol:
        return None
    if not isinstance(kind, str) or not kind:
        return None
    return CodeUnitKey(path=path, symbol=symbol, kind=kind)


def _profile_from_cache(raw_profile: dict[str, Any]) -> DuplicateProfile | None:
    """Build a duplicate profile from a YAML cache dictionary."""
    version = raw_profile.get("version")
    if version != _PROFILE_VERSION:
        return None
    keys = _keys_from_cache(raw_profile.get("keys"))
    fingerprint = _fingerprint_from_cache(raw_profile.get("source_fingerprint"))
    if keys is None or fingerprint is None:
        return None
    return DuplicateProfile(
        version=_PROFILE_VERSION,
        confidence=str(raw_profile.get("confidence") or "low"),
        structure=_structure_from_cache(raw_profile.get("structure")),
        outcome=_outcome_from_cache(raw_profile.get("outcome")),
        interface=_interface_from_cache(raw_profile.get("interface")),
        keys=keys,
        source_fingerprint=fingerprint,
        local=_local_from_cache(raw_profile.get("local")),
        imports=_imports_from_cache(raw_profile.get("imports")),
        calls=_calls_from_cache(raw_profile.get("calls")),
        attributes=_attributes_from_cache(raw_profile.get("attributes")),
        domain=_domain_from_cache(raw_profile.get("domain")),
        children=_children_from_cache(raw_profile.get("children")),
    )


def _cache_profile_is_valid(profile: DuplicateProfile, fingerprint: SourceFingerprint) -> bool:
    """Return whether a cached profile still matches current source evidence."""
    if profile.source_fingerprint is None:
        return False
    return (
        profile.source_fingerprint.analyzer_version == fingerprint.analyzer_version
        and profile.source_fingerprint.local_hash == fingerprint.local_hash
        and profile.source_fingerprint.dependency_hash == fingerprint.dependency_hash
    )


def _keys_from_cache(raw_keys: Any) -> DuplicateProfileKeys | None:
    """Build keys from a cache dictionary."""
    if not isinstance(raw_keys, dict):
        return None
    return DuplicateProfileKeys(
        duplicate_key=_optional_string(raw_keys.get("duplicate_key")),
        duplicate_hash=_optional_string(raw_keys.get("duplicate_hash")),
        hash_strength=str(raw_keys.get("hash_strength") or "ignored"),
        reason=_optional_string(raw_keys.get("reason")),
        duplicated=str(raw_keys.get("duplicated") or "no"),
        group_size=_int_value(raw_keys.get("group_size")),
    )


def _fingerprint_from_cache(raw_fingerprint: Any) -> SourceFingerprint | None:
    """Build a source fingerprint from a cache dictionary."""
    if not isinstance(raw_fingerprint, dict):
        return None
    analyzer_version = raw_fingerprint.get("analyzer_version")
    local_hash = raw_fingerprint.get("local_hash")
    dependency_hash = raw_fingerprint.get("dependency_hash")
    if not isinstance(analyzer_version, str) or not isinstance(local_hash, str):
        return None
    if not isinstance(dependency_hash, str):
        dependency_hash = ""
    return SourceFingerprint(analyzer_version, local_hash, dependency_hash)


def _structure_from_cache(raw_value: Any) -> StructureProfile:
    """Build a structure profile from cache data."""
    if not isinstance(raw_value, dict):
        return StructureProfile()
    return StructureProfile(
        normalized_ast_hash=_optional_string(raw_value.get("normalized_ast_hash")),
        return_expression_hash=_optional_string(raw_value.get("return_expression_hash")),
        trivial_wrapper=bool(raw_value.get("trivial_wrapper")),
        wrapper_target=_optional_string(raw_value.get("wrapper_target")),
    )


def _outcome_from_cache(raw_value: Any) -> OutcomeProfile:
    """Build an outcome profile from cache data."""
    if not isinstance(raw_value, dict):
        return OutcomeProfile()
    return OutcomeProfile(
        action=_optional_string(raw_value.get("action")),
        resource=_optional_string(raw_value.get("resource")),
        target=_optional_string(raw_value.get("target")),
        output=_optional_string(raw_value.get("output")),
        outcome_key=_optional_string(raw_value.get("outcome_key")),
        evidence=_tuple_of_strings(raw_value.get("evidence")),
        calls=_tuple_of_strings(raw_value.get("calls")),
        raises=_tuple_of_strings(raw_value.get("raises")),
        mutations=_tuple_of_strings(raw_value.get("mutations")),
    )


def _interface_from_cache(raw_value: Any) -> InterfaceProfile:
    """Build an interface profile from cache data."""
    if not isinstance(raw_value, dict):
        return InterfaceProfile()
    return InterfaceProfile(
        inputs=_tuple_of_strings(raw_value.get("inputs")),
        output=_optional_string(raw_value.get("output")),
        interface_hash=_optional_string(raw_value.get("interface_hash")),
    )


def _local_from_cache(raw_value: Any) -> LocalEvidence | None:
    """Build local evidence from cache data."""
    if not isinstance(raw_value, dict):
        return None
    return LocalEvidence(
        path=str(raw_value.get("path") or ""),
        symbol=str(raw_value.get("symbol") or ""),
        kind=str(raw_value.get("kind") or ""),
        decorators=_tuple_of_strings(raw_value.get("decorators")),
        constants=_tuple_of_strings(raw_value.get("constants")),
    )


def _imports_from_cache(raw_value: Any) -> ImportEvidence:
    """Build import evidence from cache data."""
    if not isinstance(raw_value, dict):
        return ImportEvidence()
    return ImportEvidence(used=_tuple_of_strings(raw_value.get("used")))


def _calls_from_cache(raw_value: Any) -> CallGraphEvidence:
    """Build call graph evidence from cache data."""
    if not isinstance(raw_value, dict):
        return CallGraphEvidence()
    return CallGraphEvidence(
        direct=_tuple_of_strings(raw_value.get("direct")),
        resolved_internal=_tuple_of_strings(raw_value.get("resolved_internal")),
        unresolved=_tuple_of_strings(raw_value.get("unresolved")),
    )


def _attributes_from_cache(raw_value: Any) -> AttributeEvidence:
    """Build attribute evidence from cache data."""
    if not isinstance(raw_value, dict):
        return AttributeEvidence()
    return AttributeEvidence(
        reads=_tuple_of_strings(raw_value.get("reads")),
        writes=_tuple_of_strings(raw_value.get("writes")),
        provenance=_tuple_of_strings(raw_value.get("provenance")),
    )


def _domain_from_cache(raw_value: Any) -> DomainEvidence:
    """Build domain evidence from cache data."""
    if not isinstance(raw_value, dict):
        return DomainEvidence()
    signals: list[DomainSignal] = []
    for signal_value in raw_value.get("signals", []):
        if not isinstance(signal_value, dict):
            continue
        action = signal_value.get("action")
        resource = signal_value.get("resource")
        target = signal_value.get("target")
        confidence = signal_value.get("confidence")
        evidence = signal_value.get("evidence")
        if all(isinstance(value, str) for value in (action, resource, target, confidence, evidence)):
            signals.append(DomainSignal(action, resource, target, confidence, evidence))
    return DomainEvidence(detected=_tuple_of_strings(raw_value.get("detected")), signals=tuple(signals))


def _children_from_cache(raw_value: Any) -> ChildProfileEvidence:
    """Build child profile evidence from cache data."""
    if not isinstance(raw_value, dict):
        return ChildProfileEvidence()
    return ChildProfileEvidence(
        inherited_keys=_tuple_of_strings(raw_value.get("inherited_keys")),
        inherited_hashes=_tuple_of_strings(raw_value.get("inherited_hashes")),
        inherited_strengths=_tuple_of_strings(raw_value.get("inherited_strengths")),
    )


def _child_profile_evidence(child_profiles: list[DuplicateProfile]) -> ChildProfileEvidence:
    """Build inherited child duplicate evidence from child profiles."""
    inherited_keys: list[str] = []
    inherited_hashes: list[str] = []
    inherited_strengths: list[str] = []
    for child_profile in child_profiles:
        if child_profile.keys.hash_strength == "ignored":
            continue
        if child_profile.keys.duplicate_key:
            inherited_keys.append(child_profile.keys.duplicate_key)
        if child_profile.keys.duplicate_hash:
            inherited_hashes.append(child_profile.keys.duplicate_hash)
        inherited_strengths.append(child_profile.keys.hash_strength)
    return ChildProfileEvidence(
        inherited_keys=tuple(inherited_keys),
        inherited_hashes=tuple(inherited_hashes),
        inherited_strengths=tuple(inherited_strengths),
    )



def _duplicate_profile_group_is_allowed(
    group_blocks: list[dict[str, Any]],
    duplicate_hash: str | None,
    duplicate_key: str | None,
) -> bool:
    """Return whether a duplicate group has an explicit false-positive allowance."""
    if not duplicate_hash and not duplicate_key:
        return False
    return any(
        _block_allows_duplicate_profile(
            block=block,
            duplicate_hash=duplicate_hash,
            duplicate_key=duplicate_key,
        )
        for block in group_blocks
    )


def _block_allows_duplicate_profile(
    block: dict[str, Any],
    duplicate_hash: str | None,
    duplicate_key: str | None,
) -> bool:
    """Return whether one block explicitly allows a duplicate profile collision."""
    duplicate_policy = block.get("duplicate_policy")
    if not isinstance(duplicate_policy, dict):
        return False

    entries: list[Any] = []
    for field_name in (
        "allowed_active_duplicate_profiles",
        "allowed_duplicate_profiles",
        "allowed_duplicate_hashes",
    ):
        raw_entries = duplicate_policy.get(field_name)
        if isinstance(raw_entries, list):
            entries.extend(raw_entries)

    for entry in entries:
        if _duplicate_policy_entry_matches(
            entry=entry,
            duplicate_hash=duplicate_hash,
            duplicate_key=duplicate_key,
        ):
            return True
    return False


def _duplicate_policy_entry_matches(
    entry: Any,
    duplicate_hash: str | None,
    duplicate_key: str | None,
) -> bool:
    """Return whether one duplicate-policy entry matches the current collision."""
    if not isinstance(entry, dict):
        return False

    reason = entry.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return False

    entry_hash = entry.get("duplicate_hash")
    if isinstance(entry_hash, str) and duplicate_hash and entry_hash == duplicate_hash:
        return True

    entry_key = entry.get("duplicate_key")
    if isinstance(entry_key, str) and duplicate_key and entry_key == duplicate_key:
        return True

    return False


def _all_blocks_are_parallel_strategy_methods(
    group: list[tuple[dict[str, Any], DuplicateProfile]],
) -> bool:
    """Return whether a duplicate group is expected strategy polymorphism."""
    method_names: set[str] = set()
    parent_names: set[str] = set()
    for block, _profile in group:
        symbol = _block_code_value(block, "symbol")
        if not symbol or "." not in symbol:
            return False
        parts = symbol.split(".")
        method_names.add(parts[-1])
        parent_names.add(parts[-2])
    if len(method_names) != 1 or len(parent_names) < 2:
        return False
    return all(parent_name.endswith("Strategy") for parent_name in parent_names)


def _block_code_value(block: dict[str, Any], field_name: str) -> str | None:
    """Return one code field from a block when present."""
    code = block.get("code")
    if not isinstance(code, dict):
        return None
    value = code.get(field_name)
    return value if isinstance(value, str) else None


def _active_block_evidence(block: dict[str, Any]) -> dict[str, Any]:
    """Build compact evidence for one active block in a duplicate group."""
    return {
        "id": block.get("id"),
        "purpose": block.get("purpose"),
        "path": _block_code_value(block, "path"),
        "symbol": _block_code_value(block, "symbol"),
        "kind": _block_code_value(block, "kind"),
    }


def _duplicate_profile_finding(
    first_block: dict[str, Any],
    duplicate_hash: str | None,
    duplicate_key: str | None,
    hash_strength: str | None,
    reason: str | None,
    active_blocks: list[dict[str, Any]],
) -> Finding:
    """Build one duplicate active profile finding."""
    return _duplicate_profile_collision_finding(
        first_block=first_block,
        duplicate_hash=duplicate_hash,
        duplicate_key=duplicate_key,
        hash_strength=hash_strength,
        reason=reason,
        active_blocks=active_blocks,
        code=_DUPLICATE_ACTIVE_PROFILE,
        severity=FINDING_SEVERITY_BLOCK,
        message="Only one active block can own the same duplicate declaration or calculated duplicate profile.",
    )


def _duplicate_profile_review_finding(
    first_block: dict[str, Any],
    duplicate_hash: str | None,
    duplicate_key: str | None,
    hash_strength: str | None,
    reason: str | None,
    active_blocks: list[dict[str, Any]],
) -> Finding:
    """Build one non-blocking duplicate profile review finding."""
    return _duplicate_profile_collision_finding(
        first_block=first_block,
        duplicate_hash=duplicate_hash,
        duplicate_key=duplicate_key,
        hash_strength=hash_strength,
        reason=reason,
        active_blocks=active_blocks,
        code=_DUPLICATE_PROFILE_REVIEW,
        severity=FINDING_SEVERITY_WARNING,
        message="Active blocks share a similar duplicate profile and should be reviewed.",
    )


def _duplicate_profile_collision_finding(
    first_block: dict[str, Any],
    duplicate_hash: str | None,
    duplicate_key: str | None,
    hash_strength: str | None,
    reason: str | None,
    active_blocks: list[dict[str, Any]],
    code: str,
    severity: str,
    message: str,
) -> Finding:
    """Build one duplicate profile collision finding."""
    return Finding(
        source=_SOURCE,
        code=code,
        severity=severity,
        path=_block_code_value(first_block, "path"),
        symbol=_block_code_value(first_block, "symbol"),
        message=message,
        evidence={
            "duplicate_hash": duplicate_hash,
            "duplicate_key": duplicate_key,
            "hash_strength": hash_strength,
            "reason": reason,
            "active_blocks": active_blocks,
        },
    )


def _active_purpose_duplicate_groups(blocks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Return active blocks grouped by normalized duplicate purpose."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for block in blocks:
        if block.get("status") != "active":
            continue
        normalized_purpose = _normalize_duplicate_purpose(block.get("purpose"))
        if normalized_purpose is None:
            continue
        groups.setdefault(normalized_purpose, []).append(block)
    return {purpose: group for purpose, group in groups.items() if len(group) > 1}


def _normalize_duplicate_purpose(value: Any) -> str | None:
    """Return the normalized purpose used for duplicate declarations."""
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    return normalized or None


def _purpose_duplicate_key(normalized_purpose: str) -> str:
    """Return the synthetic duplicate key for one normalized purpose."""
    return f"purpose|{normalized_purpose}"


def _block_id(block: dict[str, Any]) -> str | None:
    """Return a block id when present."""
    block_id = block.get("id")
    return block_id if isinstance(block_id, str) and block_id else None


def _stable_hash(value: str | None) -> str | None:
    """Return a stable short SHA-256 hash for a non-empty value."""
    if value is None or value == "":
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _hash_tuple(values: tuple[str, ...]) -> str:
    """Return a stable hash for a tuple of string values."""
    return _stable_hash("|".join(values)) or ""


def _optional_string(value: Any) -> str | None:
    """Return a string value or None."""
    if isinstance(value, str) and value:
        return value
    return None


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    """Return a sorted tuple of strings from a list-like value."""
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))


def _int_value(value: Any) -> int:
    """Return an integer value when possible."""
    if isinstance(value, int):
        return value
    return 0


def _walk_effective_body(node: ast.AST) -> list[ast.AST]:
    """Return AST descendants while avoiding nested bodies inside class nodes.

    Class nodes often contain method bodies. Using those nested bodies as class
    evidence makes the class duplicate the methods it merely owns. Functions and
    methods are still walked normally, because their body is the actual unit.
    """
    if not isinstance(node, ast.ClassDef):
        return list(ast.walk(node))
    effective_nodes: list[ast.AST] = [node]
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        effective_nodes.extend(ast.walk(child))
    return effective_nodes

def _used_name_roots(node: ast.AST) -> set[str]:
    """Return root names referenced by an AST node."""
    names: set[str] = set()
    for child in _walk_effective_body(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            root_name = _root_name(child)
            if root_name is not None:
                names.add(root_name)
    return names


def _root_name(node: ast.AST) -> str | None:
    """Return the root name for an expression such as yaml.safe_dump."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _root_name(node.value)
    if isinstance(node, ast.Call):
        return _root_name(node.func)
    return None


def _call_texts_from_unit(unit: DiscoveredCodeUnit) -> set[str]:
    """Return compact call labels from scanner call dictionaries."""
    call_texts: set[str] = set()
    for call in unit.calls:
        if not isinstance(call, dict):
            continue
        name = call.get("name")
        context = call.get("context")
        if not isinstance(name, str) or not name:
            continue
        if isinstance(context, str) and context:
            call_texts.add(f"{context}.{name}")
        else:
            call_texts.add(name)
    return call_texts


def _short_call_from_key(key: CodeUnitKey) -> str:
    """Return the leaf symbol name for a code unit key."""
    return key.symbol.rsplit(".", 1)[-1]


def _important_string_constants(node: ast.AST) -> set[str]:
    """Return string constants that are useful duplicate targets."""
    constants: set[str] = set()
    for child in _walk_effective_body(node):
        if not isinstance(child, ast.Constant) or not isinstance(child.value, str):
            continue
        text = child.value.strip()
        if not text or len(text) > 120:
            continue
        if _looks_like_path(text) or _looks_like_endpoint(text) or _looks_like_sql(text):
            constants.add(text)
            continue
        if _looks_like_event_name(text) or _looks_like_device_name(text):
            constants.add(text)
    return constants


def _self_attribute_reads(node: ast.AST) -> set[str]:
    """Return self attributes read by the node."""
    reads: set[str] = set()
    for child in _walk_effective_body(node):
        attribute_name = _self_attribute_name(child)
        if attribute_name is not None and isinstance(child.ctx, ast.Load):
            reads.add(attribute_name)
    return reads


def _self_attribute_writes(node: ast.AST) -> set[str]:
    """Return self attributes written by the node."""
    writes: set[str] = set()
    for child in _walk_effective_body(node):
        attribute_name = _self_attribute_name(child)
        if attribute_name is not None and isinstance(child.ctx, (ast.Store, ast.Del)):
            writes.add(attribute_name)
    return writes


def _self_attribute_name(node: ast.AST) -> str | None:
    """Return self.x for an attribute expression when applicable."""
    if not isinstance(node, ast.Attribute):
        return None
    if isinstance(node.value, ast.Name) and node.value.id == "self":
        return f"self.{node.attr}"
    return None


def _safe_unparse(node: ast.AST) -> str:
    """Return a compact expression string for an AST node."""
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError, TypeError):
        return ast.dump(node, include_attributes=False)


def _deduplicate_signals(signals: list[DomainSignal]) -> list[DomainSignal]:
    """Return domain signals deduplicated by comparison key and confidence."""
    unique: dict[tuple[str, str, str], DomainSignal] = {}
    for signal in signals:
        key = (signal.action, signal.resource, signal.target)
        existing_signal = unique.get(key)
        if existing_signal is None or _confidence_rank(signal.confidence) > _confidence_rank(existing_signal.confidence):
            unique[key] = signal
    return list(unique.values())


def _confidence_rank(confidence: str) -> int:
    """Return an integer rank for confidence labels."""
    if confidence == "high":
        return 3
    if confidence == "medium":
        return 2
    return 1


def _is_generic_target(target: str | None) -> bool:
    """Return whether a target is too generic for strong duplicate matching."""
    if target is None:
        return True
    normalized_target = target.strip().lower()
    return normalized_target in _GENERIC_TARGETS


def _is_variable_file_method_target(target: str | None) -> bool:
    """Return whether a file target is only a variable method call.

    A call such as ``path.write_text`` or ``blueprint_path.write_text`` tells us
    that a file is written, but it does not identify the concrete authority file
    or responsibility being written. Concrete path constants are handled by
    domain signals and may still become strong duplicate keys.
    """
    if target is None:
        return False
    normalized_target = target.strip().lower()
    if _looks_like_path(normalized_target):
        return False
    return any(normalized_target.endswith(suffix) for suffix in _FILE_METHOD_TARGET_SUFFIXES)


def _looks_like_path(value: str) -> bool:
    """Return whether a string looks like a concrete filesystem path."""
    if value in {"/", "\\"} or value.startswith("."):
        return False
    if "/" in value or "\\" in value:
        return len(value.strip("/\\")) > 2
    return bool(re.match(r"^[A-Za-z0-9_-]+\.(yaml|yml|json|txt|py|db)$", value))


def _looks_like_endpoint(value: str) -> bool:
    """Return whether a string looks like an HTTP endpoint path."""
    return value.startswith("/") and not _looks_like_path(value[1:])


def _looks_like_sql(value: str) -> bool:
    """Return whether a string looks like an SQL statement."""
    stripped = value.strip().lower()
    if re.match(r"^(select|insert|update|delete|create table|drop|alter)\b", stripped):
        return True
    return bool(re.search(r"\bselect\b.+\bfrom\b", stripped))


def _looks_like_event_name(value: str) -> bool:
    """Return whether a string looks like an event or queue name."""
    return bool(re.match(r"^[a-z][a-z0-9_]+$", value)) and any(
        marker in value for marker in ("created", "updated", "deleted", "event", "queue", "message")
    )


def _looks_like_device_name(value: str) -> bool:
    """Return whether a string looks like a serial/GPIO device target."""
    return bool(re.match(r"^(COM\d+|GPIO\d+|pin_?\d+|/dev/\w+)", value, flags=re.IGNORECASE))


def _route_signal_from_decorator(decorator: str, constants: tuple[str, ...]) -> DomainSignal | None:
    """Return a web route signal from a decorator string when possible."""
    lower_decorator = decorator.lower()
    method = None
    for candidate in ("get", "post", "put", "patch", "delete", "route"):
        if lower_decorator.endswith(f".{candidate}") or lower_decorator == candidate:
            method = candidate.upper()
            break
    if method is None:
        return None
    endpoint = next((constant for constant in constants if constant.startswith("/")), decorator)
    return DomainSignal("route", "http_endpoint", f"{method}:{endpoint}", "high", f"decorator {decorator}")


def _first_sql_target(constants: tuple[str, ...]) -> str | None:
    """Return the first SQL-like target from constants."""
    for constant in constants:
        if _looks_like_sql(constant):
            return constant[:80]
    return None


def _dataframe_column_from_mutation(mutation: str) -> str | None:
    """Return a dataframe column name from a mutation string when possible."""
    match = re.search(r"\[['\"]([^'\"]+)['\"]\]", mutation)
    if match:
        return match.group(1)
    if "." in mutation:
        return mutation.rsplit(".", 1)[-1]
    return None


def _first_command_constant(constants: tuple[str, ...]) -> str | None:
    """Return the first command-like constant."""
    for constant in constants:
        if constant in {"git", "docker", "podman", "python", "pytest", "bash", "sh"}:
            return constant
    return None


def _first_gpio_constant(constants: tuple[str, ...]) -> str | None:
    """Return the first GPIO/device-like constant."""
    for constant in constants:
        if _looks_like_device_name(constant):
            return constant
    return None


def _first_event_constant(constants: tuple[str, ...]) -> str | None:
    """Return the first event-like constant."""
    for constant in constants:
        if _looks_like_event_name(constant):
            return constant
    return None
