from bpfw.core.catalog.writer import to_snake_case as writer_to_snake_case
from bpfw.integrations.planner.utils import to_snake_case as planner_to_snake_case
from bpfw.integrations.shared.cli_runtime import normalize_command
from bpfw.shared.text import normalize_text_command, to_snake_case


def test_to_snake_case_handles_edge_cases() -> None:
    assert to_snake_case(None) == ""
    assert to_snake_case("") == ""
    assert to_snake_case("InvoiceParser") == "invoice_parser"
    assert to_snake_case("invoice parser") == "invoice_parser"
    assert to_snake_case("invoice-parser.value") == "invoice_parser_value"


def test_to_snake_case_wrappers_match_shared_implementation() -> None:
    values = [None, "", "InvoiceParser", "invoice parser", "invoice-parser.value"]
    for value in values:
        expected = to_snake_case(value)
        assert writer_to_snake_case(value if isinstance(value, str) else "") == expected
        assert planner_to_snake_case(value) == expected


def test_runtime_normalize_command_delegates_shared_normalizer() -> None:
    sample = "  HeLLo  "
    assert normalize_command(sample) == normalize_text_command(sample)
