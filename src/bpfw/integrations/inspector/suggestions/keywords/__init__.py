"""Keyword extraction from AST for purpose and domain suggestions."""

from bpfw.integrations.inspector.suggestions.keywords.extractor import extract_block_keywords
from bpfw.integrations.inspector.suggestions.keywords.models import (
    BlockKeywordProfile,
    KeywordCandidate,
    KeywordEvidence,
    ProjectVocabulary,
)
from bpfw.integrations.inspector.suggestions.keywords.normalizer import (
    build_phrases_from_tokens,
    normalize_tokens,
)
from bpfw.integrations.inspector.suggestions.keywords.scorer import (
    compute_distinctiveness,
    deduplicate_similar,
    filter_low_confidence,
    get_confidence_level,
    score_evidence,
)
from bpfw.integrations.inspector.suggestions.keywords.tokenizer import tokenize_identifier, tokenize_text
from bpfw.integrations.inspector.suggestions.keywords.vocabulary import (
    build_project_vocabulary,
    get_vocabulary_summary,
)

__all__ = [
    # Extractor
    "extract_block_keywords",
    # Models
    "BlockKeywordProfile",
    "KeywordCandidate",
    "KeywordEvidence",
    "ProjectVocabulary",
    # Normalizer
    "build_phrases_from_tokens",
    "normalize_tokens",
    # Scorer
    "compute_distinctiveness",
    "deduplicate_similar",
    "filter_low_confidence",
    "get_confidence_level",
    "score_evidence",
    # Tokenizer
    "tokenize_identifier",
    "tokenize_text",
    # Vocabulary
    "build_project_vocabulary",
    "get_vocabulary_summary",
]