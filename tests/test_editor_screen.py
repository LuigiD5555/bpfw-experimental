import builtins

from bpfw.integrations.editor.search import SearchRecord
from bpfw.integrations.editor import screen


def _search_record(
    *,
    symbol: str = "LockSystem",
    domain: str = "lock system",
    path: str = "src/bpfw/protection/authority.py",
    purpose: str = "Manage lock system",
) -> SearchRecord:
    return SearchRecord(
        responsibility_id="lock_system",
        lifecycle="active",
        domain=domain,
        technical_label=symbol,
        path=path,
        symbol=symbol,
        location="protection/authority.py",
        start_line=10,
        end_line=40,
        purpose=purpose,
        searchable_text="lock system",
    )


def test_read_input_uses_default_prompt_for_empty_prompt(monkeypatch) -> None:
    prompts = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return "  r  "

    monkeypatch.setattr(builtins, "input", fake_input)

    assert screen.read_input("") == "r"
    assert prompts == ["> "]


def test_wait_for_enter_shows_continue_text_then_default_prompt(
    capsys, monkeypatch
) -> None:
    prompts = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return ""

    monkeypatch.setattr(builtins, "input", fake_input)

    screen.wait_for_enter()

    assert capsys.readouterr().out == "Press Enter to continue.\n"
    assert prompts == ["> "]


def test_render_results_table_uses_search_record_location(capsys) -> None:
    record = _search_record()

    screen.render_results_table(
        results=[record],
        query="lock system",
        filter_display_lines=[],
    )

    output = capsys.readouterr().out
    assert "LockSystem" in output
    assert "PURPOSE" in output
    assert "DOMAIN" in output
    assert output.index("DOMAIN") < output.index("SYMBOL")
    assert output.index("PURPOSE") < output.index("SYMBOL")
    assert "[1] location:" not in output


def test_filtered_results_table_prioritizes_location_and_codelines(capsys) -> None:
    record = _search_record()

    screen.render_results_table(
        results=[record],
        query="lock system",
        filter_display_lines=["domain=lock"],
    )

    output = capsys.readouterr().out
    assert "SYMBOL" in output
    assert "LOCATION" in output
    assert "CODELINES" in output
    assert "PURPOSE" in output
    assert output.index("PURPOSE") < output.index("SYMBOL")
    assert output.index("PURPOSE") < output.index("LOCATION")
    assert output.index("LOCATION") < output.index("CODELINES")
    assert "protection/authority.p" in output
    assert "10-40" in output
    assert "Manage" in output
    assert "[1] location:" not in output


def test_results_block_ratio_stays_between_half_and_nearly_full_screen(monkeypatch) -> None:
    monkeypatch.setattr(screen, "get_terminal_width", lambda: 100)
    record = _search_record(
        symbol="LongName" * 20,
        domain="LongDomain" * 20,
        purpose="Long purpose " * 20,
    )

    assert screen._results_block_ratio([], screen.NORMAL_RESULT_COLUMNS) == 0.50
    assert screen._results_block_ratio([record], screen.NORMAL_RESULT_COLUMNS) == 0.95


def test_results_table_render_stays_within_max_screen_width(monkeypatch, capsys) -> None:
    monkeypatch.setattr(screen, "refresh_screen", lambda: None)
    monkeypatch.setattr(screen, "get_terminal_width", lambda: 80)
    record = _search_record(
        symbol="LongName" * 20,
        domain="LongDomain" * 20,
        path="src/bpfw/protection/very_long_authority_filename.py",
        purpose="Long purpose " * 20,
    )

    screen.render_results_table(
        results=[record],
        query="lock system",
        filter_display_lines=["domain=lock"],
    )

    output_lines = capsys.readouterr().out.splitlines()
    assert max(len(line) for line in output_lines) <= 76


def test_normal_results_width_priority_is_purpose_symbol_domain() -> None:
    record = _search_record(
        symbol="LongName" * 5,
        domain="LongDomain" * 20,
        purpose="Long purpose " * 20,
    )

    _idx_width, _status_width, column_widths = screen._compute_results_column_widths(
        [record],
        total_content_width=85,
        result_columns=screen.NORMAL_RESULT_COLUMNS,
    )

    domain_width, purpose_width, symbol_width = column_widths
    assert purpose_width > domain_width
    assert symbol_width >= screen.RESULT_COLUMN_MIN_WIDTHS["symbol"]


def test_filtered_results_width_priority_is_location_symbol_purpose() -> None:
    record = _search_record(
        symbol="NameValueLongEnough",
        path="src/bpfw/protection/very_long_authority_filename.py",
        purpose="Purpose value long enough",
    )

    _idx_width, _status_width, column_widths = screen._compute_results_column_widths(
        [record],
        total_content_width=90,
        result_columns=screen.FILTERED_RESULT_COLUMNS,
    )

    purpose_width, symbol_width, location_width, codelines_width = column_widths
    assert location_width == len(record.location)
    assert symbol_width >= screen.RESULT_COLUMN_MIN_WIDTHS["symbol"]
    assert codelines_width == screen.RESULT_COLUMN_MIN_WIDTHS["codelines"]


def test_filtered_results_shrink_codelines_before_priority_columns() -> None:
    record = _search_record(
        symbol="ImportantName",
        path="src/bpfw/protection/very_long_authority_filename.py",
        purpose="Important purpose",
    )

    _idx_width, _status_width, column_widths = screen._compute_results_column_widths(
        [record],
        total_content_width=70,
        result_columns=screen.FILTERED_RESULT_COLUMNS,
    )

    purpose_width, symbol_width, location_width, codelines_width = column_widths
    assert location_width > symbol_width
    assert symbol_width >= screen.RESULT_COLUMN_MIN_WIDTHS["symbol"]
    assert codelines_width == screen.RESULT_COLUMN_MIN_WIDTHS["codelines"]


def test_priority_symbol_cell_never_uses_ellipsis_when_space_is_tight(monkeypatch, capsys) -> None:
    monkeypatch.setattr(screen, "refresh_screen", lambda: None)
    monkeypatch.setattr(screen, "get_terminal_width", lambda: 60)
    record = _search_record(
        symbol="VeryLongPrimaryNameThatCannotFullyFit",
        domain="LongDomain" * 20,
        purpose="Long purpose " * 20,
    )

    screen.render_results_table(
        results=[record],
        query="lock system",
        filter_display_lines=[],
    )

    output = capsys.readouterr().out
    assert "VeryLongPrimar" in output
    assert "VeryLongPrimar..." not in output
    assert "VeryLongPrimaryNameThatCannotFullyFit..." not in output
