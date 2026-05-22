"""Safety policy for Blueprint Engine change requests.

The policy keeps the engine mechanical. It decides whether a request has enough
approval to be applied, not whether the underlying drift interpretation is true.
"""

from bpfw.authority.blueprint_engine.models import (
    BlueprintChangeKind,
    BlueprintChangeRequest,
    BlueprintChangeSource,
)


class BlueprintEngineSafetyPolicy:
    """Validate that a change request is authorized to be applied."""

    _SAFE_MECHANICAL_KINDS: frozenset[BlueprintChangeKind] = frozenset(
        {
            BlueprintChangeKind.UPDATE_LOCATION,
            BlueprintChangeKind.UPDATE_SYMBOL,
            BlueprintChangeKind.UPDATE_CODE_REFERENCE,
        }
    )

    def validate_request(self, request: BlueprintChangeRequest) -> str | None:
        """Return a blocking reason when a request is not authorized.

        Args:
            request: Blueprint change request to validate.

        Returns:
            None when allowed, otherwise a human-readable blocked reason.
        """
        if request.human_confirmed:
            return None

        if request.source == BlueprintChangeSource.CONTROLLED_REFACTOR:
            return None

        if (
            request.source == BlueprintChangeSource.SAFE_MECHANICAL_UPDATE
            and request.kind in self._SAFE_MECHANICAL_KINDS
        ):
            evidence = request.mechanical_evidence
            if evidence is not None and evidence.is_safe_mechanical_match():
                return None
            return "Safe mechanical update requires exact one-to-one evidence."

        return "Blueprint Engine requires human confirmation for this change."
