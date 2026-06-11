from sheetgo_agent import message_parser


def _text(t):
    return {"kind": "text", "text": t}


def test_single_part_is_the_prompt_no_context():
    prompt, ctx = message_parser.parse_parts([_text("Summarize the sales")])
    assert prompt == "Summarize the sales"
    assert ctx is None


def test_empty_parts_returns_empty_prompt_and_none():
    assert message_parser.parse_parts([]) == ("", None)


def test_last_non_marker_part_is_the_prompt():
    parts = [
        _text("What are the most popular games from Nintendo in 90s?"),
        _text("For context:"),
        _text("[root_agent] said: During"),
        _text("[root_agent] said:  the 90s were great."),
        _text("In `Sales`, what were the sales of those games?"),
    ]
    prompt, ctx = message_parser.parse_parts(parts)
    assert prompt == "In `Sales`, what were the sales of those games?"
    assert ctx is not None


def test_context_drops_markers_concatenates_said_chunks_and_keeps_question():
    parts = [
        _text("What are the most popular games from Nintendo in 90s?"),
        _text("For context:"),
        _text("[root_agent] said: During"),
        _text("For context:"),
        _text("[root_agent] said:  the 90s were great."),
        _text("Current prompt"),
    ]
    _, ctx = message_parser.parse_parts(parts)
    assert ctx.startswith("Earlier conversation context:")
    assert "For context:" not in ctx
    assert "During the 90s were great." in ctx
    assert "What are the most popular games from Nintendo in 90s?" in ctx


def test_context_drops_tool_activity_lines():
    parts = [
        _text("[root_agent] called tool `google_search_tool` with parameters: {}"),
        _text("[root_agent] `google_search_tool` tool returned result: {}"),
        _text("[root_agent] said: Hello there"),
        _text("Current prompt"),
    ]
    _, ctx = message_parser.parse_parts(parts)
    assert "called tool" not in ctx
    assert "tool returned result" not in ctx
    assert "Hello there" in ctx


def test_context_blob_is_byte_capped(monkeypatch):
    import importlib
    monkeypatch.setenv("AGENT_CONTEXT_MAX_BYTES", "50")
    importlib.reload(message_parser)
    parts = [_text("[root_agent] said: " + "x" * 500), _text("prompt")]
    try:
        _, ctx = message_parser.parse_parts(parts)
        assert len(ctx) <= 50
    finally:
        monkeypatch.delenv("AGENT_CONTEXT_MAX_BYTES", raising=False)
        importlib.reload(message_parser)


def test_said_chunk_mentioning_tool_is_kept_not_dropped():
    parts = [
        _text("[root_agent] said: I called tool search to find this."),
        _text("Current prompt"),
    ]
    _, ctx = message_parser.parse_parts(parts)
    assert "I called tool search to find this." in ctx


def test_all_tool_lines_yields_no_context():
    parts = [
        _text("[root_agent] called tool x with parameters: {}"),
        _text("[root_agent] x tool returned result: {}"),
        _text("Current prompt"),
    ]
    prompt, ctx = message_parser.parse_parts(parts)
    assert prompt == "Current prompt"
    assert ctx is None


def test_non_string_text_part_is_ignored():
    parts = [
        {"kind": "text", "text": None},
        {"kind": "text", "text": "Real prompt"},
    ]
    prompt, ctx = message_parser.parse_parts(parts)
    assert prompt == "Real prompt"
    assert ctx is None
