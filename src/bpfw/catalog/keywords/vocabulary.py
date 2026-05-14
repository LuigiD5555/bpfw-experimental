"""Build and manage project vocabulary for keyword analysis."""

from typing import Any

from bpfw.catalog.keywords.evidence import extract_evidence_from_block
from bpfw.catalog.keywords.models import ProjectVocabulary
from bpfw.catalog.keywords.normalizer import normalize_tokens


def build_project_vocabulary(blocks: list[dict[str, Any]]) -> ProjectVocabulary:
    """
    Build vocabulary statistics from all blocks in the project.

    This analyzes all blocks to understand:
    - What tokens appear in the project
    - How frequently each token appears
    - How many blocks contain each token

    Args:
        blocks: List of block dictionaries from scanner.

    Returns:
        ProjectVocabulary with global statistics.
    """
    if not blocks:
        return ProjectVocabulary(
            token_frequencies={},
            block_frequencies={},
            total_blocks=0,
            total_tokens=0,
        )

    total_blocks = len(blocks)
    token_frequencies: dict[str, int] = {}
    block_frequencies: dict[str, int] = {}
    total_tokens = 0

    # Process each block
    for block in blocks:
        # Extract evidence from block
        evidence = extract_evidence_from_block(block)

        # Normalize tokens and track per-block presence
        block_tokens: set[str] = set()

        for item in evidence:
            normalized = normalize_tokens([item.raw_text])
            for token in normalized:
                # Track global frequency
                token_frequencies[token] = token_frequencies.get(token, 0) + 1
                total_tokens += 1

                # Track per-block presence
                block_tokens.add(token)

        # Update block frequencies
        for token in block_tokens:
            block_frequencies[token] = block_frequencies.get(token, 0) + 1

    return ProjectVocabulary(
        token_frequencies=token_frequencies,
        block_frequencies=block_frequencies,
        total_blocks=total_blocks,
        total_tokens=total_tokens,
    )


def get_vocabulary_summary(vocabulary: ProjectVocabulary) -> dict[str, Any]:
    """
    Get a summary of vocabulary statistics.

    Args:
        vocabulary: ProjectVocabulary to summarize.

    Returns:
        Dictionary with summary statistics.
    """
    if vocabulary.total_blocks == 0:
        return {
            "total_blocks": 0,
            "total_tokens": 0,
            "unique_tokens": 0,
            "avg_tokens_per_block": 0.0,
            "most_common_tokens": [],
            "rarest_tokens": [],
        }

    unique_tokens = len(vocabulary.token_frequencies)
    avg_tokens = vocabulary.total_tokens / vocabulary.total_blocks

    # Get most common tokens (appearing in most blocks)
    sorted_by_blocks = sorted(
        vocabulary.block_frequencies.items(),
        key=lambda x: x[1],
        reverse=True,
    )
    most_common = [
        {"token": token, "blocks": count, "frequency": vocabulary.token_frequencies[token]}
        for token, count in sorted_by_blocks[:10]
    ]

    # Get rarest tokens (appearing in fewest blocks)
    sorted_by_blocks_asc = sorted(vocabulary.block_frequencies.items(), key=lambda x: x[1])
    rarest = [
        {"token": token, "blocks": count, "frequency": vocabulary.token_frequencies[token]}
        for token, count in sorted_by_blocks_asc[:10]
    ]

    return {
        "total_blocks": vocabulary.total_blocks,
        "total_tokens": vocabulary.total_tokens,
        "unique_tokens": unique_tokens,
        "avg_tokens_per_block": avg_tokens,
        "most_common_tokens": most_common,
        "rarest_tokens": rarest,
    }