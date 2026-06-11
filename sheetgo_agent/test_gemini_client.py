# sheetgo_agent/test_gemini_client.py
from unittest.mock import patch, MagicMock

from sheetgo_agent import gemini_client

ENV = {"GCP_PROJECT_ID": "proj", "GCP_LOCATION": "us-central1"}


@patch.dict("os.environ", ENV)
def test_create_cache_returns_cache_name():
    fake_cache = MagicMock()
    fake_cache.name = "projects/x/locations/y/cachedContents/abc"
    fake_client = MagicMock()
    fake_client.caches.create.return_value = fake_cache
    with patch("sheetgo_agent.gemini_client.genai.Client", return_value=fake_client):
        ref = gemini_client.create_cache([{"a": 1}])
    assert ref == "projects/x/locations/y/cachedContents/abc"
    cfg = fake_client.caches.create.call_args.kwargs["config"]
    assert "sole source of truth" in cfg.system_instruction.lower()


@patch.dict("os.environ", ENV)
def test_create_cache_returns_none_when_create_fails():
    fake_client = MagicMock()
    fake_client.caches.create.side_effect = RuntimeError("below minimum token count")
    with patch("sheetgo_agent.gemini_client.genai.Client", return_value=fake_client):
        assert gemini_client.create_cache([{"a": 1}]) is None


@patch.dict("os.environ", ENV)
def test_analyze_with_cache_ref_sets_cached_content_and_sends_history():
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = MagicMock(text="answer")
    history = [{"role": "user", "text": "q1"}, {"role": "model", "text": "a1"}]
    with patch("sheetgo_agent.gemini_client.genai.Client", return_value=fake_client):
        out = gemini_client.analyze("q2", cache_ref="CACHE", inline_dataset=None,
                                    history=history)
    assert out == "answer"
    call = fake_client.models.generate_content.call_args
    assert call.kwargs["model"] == "gemini-2.5-flash"
    assert call.kwargs["config"].cached_content == "CACHE"
    contents = call.kwargs["contents"]
    assert len(contents) == 3
    assert contents[0]["role"] == "user" and contents[0]["parts"][0]["text"] == "q1"
    assert contents[-1]["role"] == "user" and "q2" in contents[-1]["parts"][0]["text"]


@patch.dict("os.environ", ENV)
def test_analyze_inline_includes_dataset_and_system_instruction():
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = MagicMock(text="ok")
    with patch("sheetgo_agent.gemini_client.genai.Client", return_value=fake_client):
        gemini_client.analyze("q", cache_ref=None, inline_dataset=[{"Region": "North"}],
                              history=[])
    call = fake_client.models.generate_content.call_args
    assert call.kwargs["config"].cached_content is None
    assert "sole source of truth" in call.kwargs["config"].system_instruction.lower()
    assert "North" in call.kwargs["contents"][-1]["parts"][0]["text"]


# --- Regression tests for the genai-client GC lifecycle bug ---
# These use the REAL google-genai client (api_key mode, no network) instead of
# mocking genai.Client, so they exercise the actual GC finalizer. A throwaway
# `_client().models...` temporary gets garbage-collected the moment `.models`
# is dereferenced; genai's BaseApiClient.__del__ then closes the shared httpx
# client, so by `.send()` time it raises "Cannot send a request, as the client
# has been closed." The fix is to bind the client to a local variable.
# Class-level spies receive the sub-object as `self` and so do NOT keep the
# parent Client alive — faithfully reproducing production.

def test_analyze_holds_client_ref_so_httpx_not_gc_closed(monkeypatch):
    from google import genai
    from google.genai.models import Models

    seen = {}

    def spy(self, **kwargs):
        seen["closed"] = self._api_client._httpx_client.is_closed
        return MagicMock(text="ok")

    monkeypatch.setattr(Models, "generate_content", spy)
    monkeypatch.setattr(gemini_client, "_client",
                        lambda: genai.Client(api_key="dummy"))

    gemini_client.analyze("q", inline_dataset=[{"a": 1}], history=[])
    assert seen["closed"] is False  # httpx must still be open at send time


def test_create_cache_holds_client_ref_so_httpx_not_gc_closed(monkeypatch):
    from google import genai
    from google.genai.caches import Caches

    seen = {}

    def spy(self, **kwargs):
        seen["closed"] = self._api_client._httpx_client.is_closed
        result = MagicMock()
        result.name = "cache/x"
        return result

    monkeypatch.setattr(Caches, "create", spy)
    monkeypatch.setattr(gemini_client, "_client",
                        lambda: genai.Client(api_key="dummy"))

    ref = gemini_client.create_cache([{"a": 1}])
    assert seen["closed"] is False
    assert ref == "cache/x"
