"""Fast safe YAML helpers used by BPFW authority IO."""

from typing import Any

import yaml

_FAST_SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_FAST_SAFE_DUMPER = getattr(yaml, "CSafeDumper", yaml.SafeDumper)


def load_yaml_text(text: str) -> Any:
    """Load YAML text using the fastest available safe loader.

    Args:
        text: YAML source text.

    Returns:
        Parsed YAML data.
    """
    return yaml.load(text, Loader=_FAST_SAFE_LOADER)


def dump_yaml_data(data: Any, sort_keys: bool = False, allow_unicode: bool = True) -> str:
    """Dump YAML data using the fastest available safe dumper.

    Args:
        data: YAML-compatible data.
        sort_keys: Whether mapping keys should be sorted.
        allow_unicode: Whether Unicode characters should be emitted directly.

    Returns:
        Rendered YAML text.
    """
    return yaml.dump(
        data,
        Dumper=_FAST_SAFE_DUMPER,
        sort_keys=sort_keys,
        allow_unicode=allow_unicode,
    )
