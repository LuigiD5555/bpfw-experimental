"""Test keyword extraction system with real BPFW code."""

from pathlib import Path
from bpfw.catalog.scanner import scan_python_project
from bpfw.catalog.keywords import extract_block_keywords, build_project_vocabulary, get_vocabulary_summary


def discovered_unit_to_dict(unit):
    """Convert DiscoveredCodeUnit to dict format for keyword extraction."""
    return {
        "symbol": unit.symbol,
        "kind": unit.symbol_type,
        "detected": {
            "docstring": unit.docstring,
            "parameters": [inp["name"] for inp in unit.interface_inputs],
            "return_annotation": unit.interface_output["type"] if unit.interface_output else None,
            "called_symbols": unit.called_symbols,
            "imports": unit.imports,
        },
    }


def main():
    """Test keyword extraction with real BPFW code."""

    # Scan BPFW project
    print("Scanning BPFW project...")
    scan_result = scan_python_project(
        project_root=Path("src/bpfw"),
        source_roots=["."],
        ignored_paths=["tests"],
    )

    print(f"Found {len(scan_result.discovered_units)} blocks")

    # Convert to dict format for keyword extraction
    blocks_as_dicts = [discovered_unit_to_dict(unit) for unit in scan_result.discovered_units]

    # Build vocabulary from discovered units
    print("\nBuilding project vocabulary...")
    vocabulary = build_project_vocabulary(blocks_as_dicts)

    # Print vocabulary summary
    print("\n" + "=" * 60)
    print("VOCABULARY SUMMARY")
    print("=" * 60)
    summary = get_vocabulary_summary(vocabulary)
    print(f"Total blocks: {summary['total_blocks']}")
    print(f"Total tokens: {summary['total_tokens']}")
    print(f"Unique tokens: {summary['unique_tokens']}")
    print(f"Avg tokens per block: {summary['avg_tokens_per_block']:.1f}")

    print("\nMost common tokens:")
    for item in summary['most_common_tokens'][:10]:
        freq_pct = item['blocks'] / summary['total_blocks'] * 100
        print(f"  {item['token']}: {item['blocks']} blocks ({freq_pct:.1f}%)")

    print("\nRarest tokens:")
    for item in summary['rarest_tokens'][:10]:
        freq_pct = item['blocks'] / summary['total_blocks'] * 100
        print(f"  {item['token']}: {item['blocks']} blocks ({freq_pct:.1f}%)")

    # Test a few representative blocks
    print("\n" + "=" * 60)
    print("SAMPLE BLOCKS")
    print("=" * 60)

    # Get blocks with interesting patterns
    sample_units = [
        unit for unit in scan_result.discovered_units
        if unit.docstring
    ][:5]

    for i, unit in enumerate(sample_units, 1):
        print(f"\n--- Block {i}: {unit.symbol} ---")
        print(f"Type: {unit.symbol_type}")
        print(f"Path: {unit.path}")

        # Convert to dict format for keyword extraction
        block_dict = discovered_unit_to_dict(unit)

        # Extract keywords
        profile = extract_block_keywords(block_dict, vocabulary=vocabulary)

        print("Top keywords:")
        for keyword in profile.keywords[:5]:
            sources_str = ", ".join(keyword.sources)
            print(f"  - {keyword.token}: {keyword.score:.1f} ({sources_str})")

        if profile.phrases:
            print("Phrases:")
            for phrase in profile.phrases[:3]:
                print(f"  - {phrase}")

    # Test purpose suggestions
    print("\n" + "=" * 60)
    print("PURPOSE SUGGESTIONS TEST")
    print("=" * 60)

    try:
        from bpfw.catalog.purpose_suggestions import suggest_purposes

        for i, unit in enumerate(sample_units[:3], 1):
            print(f"\n--- Block {i}: {unit.symbol} ---")
            block_dict = discovered_unit_to_dict(unit)
            suggestions = suggest_purposes(block_dict, project_blocks=blocks_as_dicts)

            for j, suggestion in enumerate(suggestions, 1):
                print(f"  [{j}] {suggestion.text}")
                print(f"      Source: {suggestion.source}")
                print(f"      Evidence: {suggestion.evidence}")
    except Exception as e:
        print(f"Error testing purpose suggestions: {e}")
        import traceback
        traceback.print_exc()

    # Test domain suggestions
    print("\n" + "=" * 60)
    print("DOMAIN SUGGESTIONS TEST")
    print("=" * 60)

    try:
        from bpfw.catalog.domain_suggestions import suggest_domains

        for i, unit in enumerate(sample_units[:3], 1):
            print(f"\n--- Block {i}: {unit.symbol} ---")
            block_dict = {
                **discovered_unit_to_dict(unit),
                "code": {
                    "path": unit.path,
                    "module": unit.module,
                    "symbol": unit.symbol,
                },
            }
            suggestions = suggest_domains(block_dict, project_blocks=blocks_as_dicts)

            for j, suggestion in enumerate(suggestions, 1):
                print(f"  [{j}] {suggestion.text}")
                print(f"      Score: {suggestion.score}")
                print(f"      Evidence: {suggestion.evidence}")
    except Exception as e:
        print(f"Error testing domain suggestions: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()