from types import SimpleNamespace
from unittest.mock import patch

from sheetgo_agent import adk_agent


def _ctx(client_id="client-abc"):
    return SimpleNamespace(state={"client_id": client_id})


def _evt(role, text, inv="other-inv", partial=False):
    part = SimpleNamespace(text=text)
    content = SimpleNamespace(role=role, parts=[part])
    return SimpleNamespace(content=content, partial=partial, invocation_id=inv)


def _analyze_ctx(active, events=None, invocation_id="cur-inv"):
    return SimpleNamespace(
        state={"active_dataset": active},
        session=SimpleNamespace(events=events or []),
        invocation_id=invocation_id,
    )


def test_load_dataset_caches_and_stores_only_metadata():
    data = [{"Region": "North", "Amount": 1}, {"Region": "South", "Amount": 2}]
    ctx = _ctx()
    with patch.dict(adk_agent.SHEETGO_API_KEYS, {"client-abc": "sg_abc"}, clear=True), \
         patch("sheetgo_agent.adk_agent.data_client.search_files",
               return_value=[{"id": "f1", "name": "Sales"}]), \
         patch("sheetgo_agent.adk_agent.data_client.fetch_dataset", return_value=data), \
         patch("sheetgo_agent.adk_agent.gemini_client.create_cache",
               return_value="projects/p/locations/l/cachedContents/c1") as mk:
        out = adk_agent.load_dataset("Sales", ctx)
    mk.assert_called_once_with(data)
    active = ctx.state["active_dataset"]
    assert active["cache_name"] == "projects/p/locations/l/cachedContents/c1"
    assert active["file_name"] == "Sales"
    assert active["row_count"] == 2
    assert "inline_dataset" not in active           # rows NOT stored on cache path
    assert "sample_rows" not in active
    # confirmation returned to the model: short, no rows
    assert out["file_name"] == "Sales"
    assert out["row_count"] == 2
    assert out["columns"] == ["Region", "Amount"]
    assert "sample_rows" not in out


def test_load_dataset_inline_fallback_when_cache_unavailable():
    data = [{"Region": "North", "Amount": 1}]
    ctx = _ctx()
    with patch.dict(adk_agent.SHEETGO_API_KEYS, {"client-abc": "sg_abc"}, clear=True), \
         patch("sheetgo_agent.adk_agent.data_client.search_files",
               return_value=[{"id": "f1", "name": "Small"}]), \
         patch("sheetgo_agent.adk_agent.data_client.fetch_dataset", return_value=data), \
         patch("sheetgo_agent.adk_agent.gemini_client.create_cache", return_value=None):
        out = adk_agent.load_dataset("Small", ctx)
    active = ctx.state["active_dataset"]
    assert active.get("cache_name") is None
    assert active["inline_dataset"] == data         # rows kept for inline analyze
    assert active["file_name"] == "Small"
    assert out["row_count"] == 1


def test_load_dataset_resolves_per_client_key_calls_search_and_fetch():
    data = [{"Region": "North", "Amount": 1}, {"Region": "South", "Amount": 2}]
    ctx = _ctx()
    with patch.dict(adk_agent.SHEETGO_API_KEYS, {"client-abc": "sg_abc"}, clear=True), \
         patch("sheetgo_agent.adk_agent.data_client.search_files",
               return_value=[{"id": "f1", "name": "Sales"}]) as search, \
         patch("sheetgo_agent.adk_agent.data_client.fetch_dataset", return_value=data) as fetch, \
         patch("sheetgo_agent.adk_agent.gemini_client.create_cache",
               return_value="projects/p/locations/l/cachedContents/c1"):
        out = adk_agent.load_dataset("Sales", ctx)
    search.assert_called_once_with("Sales", "sg_abc")
    fetch.assert_called_once_with("f1", "sg_abc")
    assert out["file_name"] == "Sales"
    assert out["row_count"] == 2
    assert out["columns"] == ["Region", "Amount"]
    assert "sample_rows" not in out


def test_load_dataset_unauthenticated_when_client_not_mapped():
    with patch.dict(adk_agent.SHEETGO_API_KEYS, {}, clear=True), \
         patch("sheetgo_agent.adk_agent.data_client.search_files") as search:
        out = adk_agent.load_dataset("Sales", _ctx("unknown-client"))
    assert "error" in out and "not authenticated for sheetgo" in out["error"].lower()
    search.assert_not_called()


def test_load_dataset_not_found_returns_error():
    with patch.dict(adk_agent.SHEETGO_API_KEYS, {"client-abc": "sg_abc"}, clear=True), \
         patch("sheetgo_agent.adk_agent.data_client.search_files", return_value=[]):
        out = adk_agent.load_dataset("Ghost", _ctx())
    assert "error" in out and "couldn't find" in out["error"].lower()


def test_load_dataset_empty_dataset_has_empty_schema():
    ctx = _ctx()
    with patch.dict(adk_agent.SHEETGO_API_KEYS, {"client-abc": "sg_abc"}, clear=True), \
         patch("sheetgo_agent.adk_agent.data_client.search_files",
               return_value=[{"id": "f1", "name": "Empty"}]), \
         patch("sheetgo_agent.adk_agent.data_client.fetch_dataset", return_value=[]), \
         patch("sheetgo_agent.adk_agent.gemini_client.create_cache", return_value=None):
        out = adk_agent.load_dataset("Empty", ctx)
    assert out["row_count"] == 0
    assert out["columns"] == []
    assert "sample_rows" not in out


def test_build_agent_registers_tool_without_cache_callback():
    agent = adk_agent.build_agent()
    assert agent.name == "sheetgo_data_agent"
    tool_names = [getattr(t, "name", getattr(t, "__name__", "")) for t in agent.tools]
    assert any("load_dataset" in n for n in tool_names)
    # Explicit caching removed (incompatible with ADK tools) -> no before_model_callback.
    assert not agent.before_model_callback


def test_build_agent_configures_http_retry():
    agent = adk_agent.build_agent()
    ro = agent.generate_content_config.http_options.retry_options
    assert ro.attempts == 2
    assert ro.initial_delay == 1
    assert 429 in ro.http_status_codes


def test_vertex_backend_env_configured_on_import(monkeypatch):
    import importlib
    import os
    monkeypatch.setenv("GCP_PROJECT_ID", "proj-x")
    monkeypatch.setenv("GCP_LOCATION", "europe-west1")
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    importlib.reload(adk_agent)
    assert os.environ["GOOGLE_GENAI_USE_VERTEXAI"] == "TRUE"
    assert os.environ["GOOGLE_CLOUD_PROJECT"] == "proj-x"
    assert os.environ["GOOGLE_CLOUD_LOCATION"] == "europe-west1"


def test_analyze_uses_cache_ref_and_history():
    active = {"file_name": "Sales", "row_count": 2, "cache_name": "projects/p/.../c1"}
    events = [
        _evt("user", "earlier question", inv="old"),
        _evt("model", "earlier answer", inv="old"),
        _evt("user", "current q", inv="cur-inv"),          # current turn -> excluded
    ]
    ctx = _analyze_ctx(active, events, invocation_id="cur-inv")
    with patch("sheetgo_agent.adk_agent.gemini_client.analyze", return_value="ANSWER") as az:
        out = adk_agent.analyze("How many sales?", ctx)
    assert out == "ANSWER"
    _, kwargs = az.call_args
    assert kwargs["cache_ref"] == "projects/p/.../c1"
    assert kwargs["inline_dataset"] is None
    # history excludes the current-invocation event, keeps the two old ones, role from content.role
    assert kwargs["history"] == [
        {"role": "user", "text": "earlier question"},
        {"role": "model", "text": "earlier answer"},
    ]


def test_analyze_inline_when_no_cache():
    data = [{"a": 1}]
    active = {"file_name": "Small", "row_count": 1, "cache_name": None, "inline_dataset": data}
    ctx = _analyze_ctx(active, events=[])
    with patch("sheetgo_agent.adk_agent.gemini_client.analyze", return_value="OK") as az:
        out = adk_agent.analyze("q", ctx)
    _, kwargs = az.call_args
    assert kwargs["cache_ref"] is None
    assert kwargs["inline_dataset"] == data
    assert out == "OK"


def test_analyze_no_dataset_loaded_asks_to_load():
    ctx = _analyze_ctx(active=None, events=[])
    ctx.state = {}  # no active_dataset
    with patch("sheetgo_agent.adk_agent.gemini_client.analyze") as az:
        out = adk_agent.analyze("q", ctx)
    az.assert_not_called()
    assert "load" in out.lower()  # guidance to load a dataset first


def test_analyze_skips_partial_and_textless_events():
    active = {"file_name": "S", "row_count": 1, "cache_name": "c1"}
    fc = SimpleNamespace(text=None)  # function-call-like part, no text
    textless = SimpleNamespace(content=SimpleNamespace(role="model", parts=[fc]), partial=False, invocation_id="old")
    partial = _evt("model", "streaming...", inv="old", partial=True)
    good = _evt("user", "keep me", inv="old")
    ctx = _analyze_ctx(active, [textless, partial, good], invocation_id="cur")
    with patch("sheetgo_agent.adk_agent.gemini_client.analyze", return_value="A") as az:
        adk_agent.analyze("q", ctx)
    assert az.call_args.kwargs["history"] == [{"role": "user", "text": "keep me"}]


def test_build_agent_registers_load_and_analyze():
    agent = adk_agent.build_agent()
    names = [getattr(t, "name", getattr(t, "__name__", "")) for t in agent.tools]
    assert any("load_dataset" in n for n in names)
    assert any("analyze" in n for n in names)


def test_analyze_history_feeds_through_gemini_client_build_contents():
    """Regression: _history_from_events output must satisfy gemini_client._build_contents
    (flat {role,text}). Mocks only the genai client, so the real analyze+_build_contents run."""
    from unittest.mock import MagicMock
    active = {"file_name": "S", "row_count": 1, "cache_name": "projects/p/.../c1"}
    events = [_evt("user", "prior q", inv="old"), _evt("model", "prior a", inv="old")]
    ctx = _analyze_ctx(active, events, invocation_id="cur")
    fake_resp = MagicMock()
    fake_resp.text = "FINAL"
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_resp
    with patch("sheetgo_agent.gemini_client._client", return_value=fake_client):
        out = adk_agent.analyze("How many?", ctx)
    assert out == "FINAL"
    # the contents actually sent to genai: prior turns (flat->parts) + current question
    sent = fake_client.models.generate_content.call_args.kwargs["contents"]
    assert sent[0] == {"role": "user", "parts": [{"text": "prior q"}]}
    assert sent[1] == {"role": "model", "parts": [{"text": "prior a"}]}
    assert sent[-1]["role"] == "user"
    assert "How many?" in sent[-1]["parts"][0]["text"]
