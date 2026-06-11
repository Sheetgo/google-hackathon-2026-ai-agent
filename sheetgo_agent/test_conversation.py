from unittest.mock import patch, MagicMock

import importlib


def _fresh_module(max_turns="10", ttl="3600"):
    """Import conversation with a mocked cache and known env."""
    env = {"AGENT_CONV_TTL": ttl}
    if max_turns is not None:
        env["AGENT_HISTORY_MAX_TURNS"] = max_turns
    with patch.dict("os.environ", env, clear=False):
        import os as _os
        if max_turns is None:
            _os.environ.pop("AGENT_HISTORY_MAX_TURNS", None)
        import sheetgo_agent.conversation as conv
        importlib.reload(conv)
        return conv


def test_load_returns_none_when_absent():
    conv = _fresh_module()
    with patch.object(conv, "cache") as cache:
        cache.get.return_value = None
        assert conv.load("C1") is None
        cache.get.assert_called_once_with(key="ai-agent-conv:C1")


def test_save_writes_state_with_ttl_and_key():
    conv = _fresh_module(ttl="123")
    with patch.object(conv, "cache") as cache:
        state = conv.save("C1", file_id="f1", cache_ref="r1",
                          inline_dataset=None,
                          history=[{"role": "user", "text": "hi"}])
    cache.set.assert_called_once()
    kwargs = cache.set.call_args.kwargs
    assert kwargs["key"] == "ai-agent-conv:C1"
    assert kwargs["time"] == 123
    assert kwargs["val"]["file_id"] == "f1"
    assert kwargs["val"]["cache_ref"] == "r1"
    assert state["history"] == [{"role": "user", "text": "hi"}]


def test_append_trims_to_sliding_window():
    conv = _fresh_module(max_turns="4")
    existing = {"file_id": "f1", "cache_ref": "r1", "inline_dataset": None,
                "history": [{"role": "user", "text": "1"},
                            {"role": "model", "text": "2"},
                            {"role": "user", "text": "3"},
                            {"role": "model", "text": "4"}]}
    with patch.object(conv, "cache") as cache:
        cache.get.return_value = dict(existing)
        conv.append("C1", {"role": "user", "text": "5"},
                          {"role": "model", "text": "6"})
    written = cache.set.call_args.kwargs["val"]["history"]
    assert written == [{"role": "user", "text": "3"},
                       {"role": "model", "text": "4"},
                       {"role": "user", "text": "5"},
                       {"role": "model", "text": "6"}]


def test_append_noop_when_no_state():
    conv = _fresh_module()
    with patch.object(conv, "cache") as cache:
        cache.get.return_value = None
        assert conv.append("C1", {"role": "user", "text": "x"},
                                 {"role": "model", "text": "y"}) is None
        cache.set.assert_not_called()


def test_save_stores_context_turn():
    conv = _fresh_module()
    with patch.object(conv, "cache") as cache:
        conv.save("C1", file_id="f1", cache_ref="r1", inline_dataset=None,
                  history=[{"role": "user", "text": "hi"}],
                  context_turn={"role": "user", "text": "ctx"})
    val = cache.set.call_args.kwargs["val"]
    assert val["context_turn"] == {"role": "user", "text": "ctx"}


def test_save_context_turn_defaults_none():
    conv = _fresh_module()
    with patch.object(conv, "cache") as cache:
        conv.save("C1", file_id="f1", cache_ref=None, inline_dataset=None, history=[])
    assert cache.set.call_args.kwargs["val"]["context_turn"] is None


def test_append_refreshes_context_turn_when_given():
    conv = _fresh_module()
    existing = {"file_id": "f1", "cache_ref": "r1", "inline_dataset": None,
                "context_turn": {"role": "user", "text": "old"},
                "history": [{"role": "user", "text": "1"}]}
    with patch.object(conv, "cache") as cache:
        cache.get.return_value = dict(existing)
        conv.append("C1", {"role": "user", "text": "2"}, {"role": "model", "text": "3"},
                    context_turn={"role": "user", "text": "new"})
    assert cache.set.call_args.kwargs["val"]["context_turn"] == {"role": "user", "text": "new"}


def test_append_keeps_context_turn_when_not_given():
    conv = _fresh_module()
    existing = {"file_id": "f1", "cache_ref": "r1", "inline_dataset": None,
                "context_turn": {"role": "user", "text": "old"}, "history": []}
    with patch.object(conv, "cache") as cache:
        cache.get.return_value = dict(existing)
        conv.append("C1", {"role": "user", "text": "2"}, {"role": "model", "text": "3"})
    assert cache.set.call_args.kwargs["val"]["context_turn"] == {"role": "user", "text": "old"}


def test_combined_history_prepends_context_turn():
    conv = _fresh_module()
    state = {"context_turn": {"role": "user", "text": "ctx"},
             "history": [{"role": "user", "text": "a"}, {"role": "model", "text": "b"}]}
    assert conv.combined_history(state) == [
        {"role": "user", "text": "ctx"},
        {"role": "user", "text": "a"},
        {"role": "model", "text": "b"},
    ]


def test_combined_history_without_context_turn():
    conv = _fresh_module()
    state = {"context_turn": None, "history": [{"role": "user", "text": "a"}]}
    assert conv.combined_history(state) == [{"role": "user", "text": "a"}]


def test_default_max_turns_is_20():
    conv = _fresh_module(max_turns=None)
    assert conv.MAX_TURNS == 20
