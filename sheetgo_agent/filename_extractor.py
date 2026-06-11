# sheetgo_agent/filename_extractor.py
"""Extract the dataset filename from a user prompt.

Strategy: take the first single-, double-, or backtick-quoted substring; if
there are no quotes, fall back to a Gemini extraction call.
"""
import re

from . import gemini_client

_QUOTED = re.compile(r"(?:^|(?<=\s))'([^']+)'|\"([^\"]+)\"|`([^`]+)`")


def extract_filename(text: str | None) -> str | None:
    """Return the filename mentioned in `text`, or None.

    Prefers a quoted name: a single-quoted name must be preceded by
    start-of-string or whitespace (so possessive apostrophes like "John's"
    don't false-match); double-quoted and backtick-quoted names match anywhere.
    With no quoted name, falls back to a Gemini extraction call.
    """
    if not text:
        return None
    match = _QUOTED.search(text)
    if match:
        name = (match.group(1) or match.group(2) or match.group(3)).strip()
        return name or None
    return gemini_client.extract_filename_llm(text)
