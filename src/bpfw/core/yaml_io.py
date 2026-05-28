"""PURPOSE fast safe YAML helpers used by BPFW authority IO
DOMAIN  framework core
"""

from typing import Any

import yaml

_FAST_SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_FAST_SAFE_DUMPER = getattr(yaml, "CSafeDumper", yaml.SafeDumper)


def load_yaml_text(text: str) -> Any:
    """PURPOSE read YAML text using the fastest available safe loader
    DOMAIN  framework core
    """
    return yaml.load(text, Loader=_FAST_SAFE_LOADER)


def dump_yaml_data(data: Any, sort_keys: bool = False, allow_unicode: bool = True) -> str:
    """PURPOSE dump YAML data using the fastest available safe dumper
    DOMAIN  framework core
    """
    return yaml.dump(
        data,
        Dumper=_FAST_SAFE_DUMPER,
        sort_keys=sort_keys,
        allow_unicode=allow_unicode,
    )
