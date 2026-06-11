from unittest.mock import patch

from sheetgo_agent import filename_extractor


def test_extracts_single_quoted_name():
    assert filename_extractor.extract_filename(
        "In 'Products Sales', show top 5") == "Products Sales"


def test_extracts_double_quoted_name():
    assert filename_extractor.extract_filename(
        'Analyze "Q1 Report" please') == "Q1 Report"


def test_falls_back_to_llm_when_no_quotes():
    with patch("sheetgo_agent.filename_extractor.gemini_client.extract_filename_llm",
               return_value="Products Sales") as llm:
        result = filename_extractor.extract_filename("look at products sales data")
    assert result == "Products Sales"
    llm.assert_called_once_with("look at products sales data")


def test_returns_none_when_llm_finds_nothing():
    with patch("sheetgo_agent.filename_extractor.gemini_client.extract_filename_llm",
               return_value=None):
        assert filename_extractor.extract_filename("hello there") is None


def test_empty_text_returns_none_without_calling_llm():
    with patch("sheetgo_agent.filename_extractor.gemini_client.extract_filename_llm") as llm:
        assert filename_extractor.extract_filename("") is None
        llm.assert_not_called()


def test_ignores_possessive_apostrophe_before_quoted_name():
    assert filename_extractor.extract_filename(
        "Show John's 'sales.csv' data") == "sales.csv"


def test_mismatched_quotes_fall_back_to_llm():
    with patch("sheetgo_agent.filename_extractor.gemini_client.extract_filename_llm",
               return_value=None) as llm:
        assert filename_extractor.extract_filename("weird 'foo\" text") is None
    llm.assert_called_once()


def test_extracts_backtick_quoted_name():
    assert filename_extractor.extract_filename(
        "In `Hundred Game Industry Sales`, show sales") == "Hundred Game Industry Sales"


def test_backtick_takes_precedence_over_llm():
    from unittest.mock import patch
    with patch("sheetgo_agent.filename_extractor.gemini_client.extract_filename_llm") as llm:
        assert filename_extractor.extract_filename("use `Q1 Data` now") == "Q1 Data"
        llm.assert_not_called()
