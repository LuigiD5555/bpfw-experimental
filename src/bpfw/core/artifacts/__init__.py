"""First-class artifact resolution and flow discovery."""
from bpfw.core.artifacts.models import ResolvedArtifact
from bpfw.core.artifacts.resolver import ArtifactResolver, choose_primary_artifact, block_artifacts

__all__ = ["ResolvedArtifact", "ArtifactResolver", "choose_primary_artifact", "block_artifacts"]
