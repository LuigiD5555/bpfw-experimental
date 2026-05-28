"""PURPOSE safety policy for Blueprint Engine change requests
DOMAIN  approved blueprint changes
"""

from bpfw.core.blueprint_engine.models import (
    BlueprintChangeKind,
    BlueprintChangeRequest,
    BlueprintChangeSource,
)


class BlueprintEngineSafetyPolicy:
    """PURPOSE check that a change request is authorized to be applied
    DOMAIN  approved blueprint changes
    """

    _SAFE_MECHANICAL_KINDS: frozenset[BlueprintChangeKind] = frozenset(
        {
            BlueprintChangeKind.UPDATE_LOCATION,
            BlueprintChangeKind.UPDATE_SYMBOL,
            BlueprintChangeKind.UPDATE_CODE_REFERENCE,
        }
    )

    def validate_request(self, request: BlueprintChangeRequest) -> str | None:
        """PURPOSE get a blocking reason when a request is not authorized
        DOMAIN  approved blueprint changes
        """
        if request.human_confirmed:
            return None

        if (
            request.source
            in {
                BlueprintChangeSource.SAFE_MECHANICAL_UPDATE,
                BlueprintChangeSource.CONTROLLED_REFACTOR,
            }
            and request.kind in self._SAFE_MECHANICAL_KINDS
        ):
            evidence = request.mechanical_evidence
            if evidence is not None and evidence.is_safe_mechanical_match():
                return None
            return "Safe mechanical update requires exact one-to-one evidence."

        return "Blueprint Engine requires human confirmation for this change."
