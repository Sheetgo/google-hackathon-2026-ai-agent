import asyncio
from unittest.mock import patch, MagicMock

from sheetgo_agent import adk_session


def test_run_turn_returns_final_text(monkeypatch):
    final = MagicMock()
    final.is_final_response.return_value = True
    part = MagicMock(); part.text = "the answer"
    final.content.parts = [part]
    fake_runner = MagicMock()
    fake_runner.run.return_value = iter([final])

    # avoid building a real agent / hitting ADK internals
    monkeypatch.setattr(adk_session, "build_agent", lambda: MagicMock())
    monkeypatch.setattr(adk_session, "Runner", lambda **kw: fake_runner)
    # session ensure is a no-op for this test
    monkeypatch.setattr(adk_session, "_ensure_session", lambda svc, cid, client_id=None: None)

    out = adk_session.run_turn("C1", "What are the sales?")
    assert out == "the answer"
    # the message text reached the runner
    assert fake_runner.run.call_args.kwargs["new_message"].parts[0].text == "What are the sales?"


def test_final_text_concatenates_parts_of_final_event():
    e1 = MagicMock(); e1.is_final_response.return_value = False
    e2 = MagicMock(); e2.is_final_response.return_value = True
    p1 = MagicMock(); p1.text = "Hello "
    p2 = MagicMock(); p2.text = "world"
    e2.content.parts = [p1, p2]
    assert adk_session._final_text([e1, e2]) == "Hello world"


def test_final_text_handles_final_event_with_no_content():
    from unittest.mock import MagicMock
    e = MagicMock()
    e.is_final_response.return_value = True
    e.content = None
    assert adk_session._final_text([e]) == ""


def test_session_service_round_trips_through_cache():
    svc = adk_session.MemcachedSessionService()
    store = {}
    fake_cache = MagicMock()
    fake_cache.set.side_effect = lambda key, val, time=0: store.__setitem__(key, val)
    fake_cache.get.side_effect = lambda key: store.get(key)
    with patch.object(adk_session, "cache", fake_cache):
        created = asyncio.run(svc.create_session(app_name="sheetgo_data_agent",
                                                 user_id="u", session_id="C1"))
        got = asyncio.run(svc.get_session(app_name="sheetgo_data_agent",
                                          user_id="u", session_id="C1"))
    assert got is not None
    assert got.id == created.id


def test_run_turn_returns_quota_message_on_429(monkeypatch):
    from unittest.mock import MagicMock
    fake_runner = MagicMock()
    fake_runner.run.side_effect = RuntimeError(
        "429 RESOURCE_EXHAUSTED. Resource has been exhausted (e.g. check quota)."
    )
    monkeypatch.setattr(adk_session, "build_agent", lambda: MagicMock())
    monkeypatch.setattr(adk_session, "Runner", lambda **kw: fake_runner)
    monkeypatch.setattr(adk_session, "_ensure_session", lambda svc, cid, client_id=None: None)
    out = adk_session.run_turn("C1", "hi")
    assert out == adk_session.QUOTA_MESSAGE
    assert "try again" in out.lower()


def test_run_turn_returns_generic_message_on_other_error(monkeypatch):
    from unittest.mock import MagicMock
    fake_runner = MagicMock()
    fake_runner.run.side_effect = RuntimeError("some other failure")
    monkeypatch.setattr(adk_session, "build_agent", lambda: MagicMock())
    monkeypatch.setattr(adk_session, "Runner", lambda **kw: fake_runner)
    monkeypatch.setattr(adk_session, "_ensure_session", lambda svc, cid, client_id=None: None)
    out = adk_session.run_turn("C1", "hi")
    assert out == adk_session.GENERIC_MESSAGE


def test_run_turn_returns_generic_message_when_no_final_text(monkeypatch):
    from unittest.mock import MagicMock
    fake_runner = MagicMock()
    fake_runner.run.return_value = iter([])  # no final-response event
    monkeypatch.setattr(adk_session, "build_agent", lambda: MagicMock())
    monkeypatch.setattr(adk_session, "Runner", lambda **kw: fake_runner)
    monkeypatch.setattr(adk_session, "_ensure_session", lambda svc, cid, client_id=None: None)
    out = adk_session.run_turn("C1", "hi")
    assert out == adk_session.GENERIC_MESSAGE


def test_run_turn_passes_client_id_to_ensure_session(monkeypatch):
    from unittest.mock import MagicMock
    captured = {}
    fake_runner = MagicMock(); fake_runner.run.return_value = iter([])
    monkeypatch.setattr(adk_session, "build_agent", lambda: MagicMock())
    monkeypatch.setattr(adk_session, "Runner", lambda **kw: fake_runner)
    monkeypatch.setattr(adk_session, "_ensure_session",
                        lambda svc, cid, client_id=None: captured.update(client_id=client_id))
    adk_session.run_turn("C1", "hi", "client-xyz")
    assert captured["client_id"] == "client-xyz"
