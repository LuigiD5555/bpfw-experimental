"""Data models for keyword extraction system."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KeywordEvidence:
    """Stores one raw keyword candidate and the source where it was found."""

    raw_text: str
    source: str
    weight: float
    location: str | None = None


@dataclass(frozen=True, slots=True)
class KeywordCandidate:
    """Stores a normalized keyword candidate with accumulated evidence."""

    token: str
    score: float
    sources: list[str]
    occurrences: int


@dataclass(frozen=True, slots=True)
class BlockKeywordProfile:
    """Stores ranked keywords for one code block."""

    block_id: str
    keywords: list[KeywordCandidate]
    phrases: list[str]


@dataclass(frozen=True, slots=True)
class ProjectVocabulary:
    """Stores global vocabulary statistics for the entire project."""

    token_frequencies: dict[str, int]
    block_frequencies: dict[str, int]
    total_blocks: int
    total_tokens: int

    def get_token_block_frequency(self, token: str) -> float:
        """Get what fraction of blocks contain this token."""
        if self.total_blocks == 0:
            return 0.0
        return self.block_frequencies.get(token, 0) / self.total_blocks

    def get_token_global_frequency(self, token: str) -> float:
        """Get what fraction of all tokens this represents."""
        if self.total_tokens == 0:
            return 0.0
        return self.token_frequencies.get(token, 0) / self.total_tokens

    def is_common_token(self, token: str, threshold: float = 0.7) -> bool:
        """Check if token appears in more than threshold fraction of blocks."""
        return self.get_token_block_frequency(token) > threshold

    def is_rare_token(self, token: str, threshold: float = 0.1) -> bool:
        """Check if token appears in less than threshold fraction of blocks."""
        return self.get_token_block_frequency(token) < threshold