import json
from unittest.mock import patch, MagicMock
import pytest
from sheetgo_agent import data_client

ENV = {"CORE_API_BASE_URL": "https://api.example.com"}


def _resp(status_code, json_data=None, text=""):
    r = MagicMock(); r.status_code = status_code; r.json.return_value = json_data; r.text = text
    return r


@patch.dict("os.environ", ENV)
def test_fetch_dataset_uses_passed_api_key():
    with patch("sheetgo_agent.data_client.requests.get",
               return_value=_resp(200, [{"a": 1}])) as get:
        data_client.fetch_dataset("FILE123", "sg_client_key")
    assert get.call_args[0][0] == "https://api.example.com/rest/beta/files/FILE123"
    assert get.call_args[1]["headers"]["Authorization"] == "Bearer sg_client_key"


@patch.dict("os.environ", ENV)
def test_fetch_dataset_non_200_raises():
    with patch("sheetgo_agent.data_client.requests.get", return_value=_resp(503, text="down")):
        with pytest.raises(data_client.DataFetchError):
            data_client.fetch_dataset("F", "sg_k")


@patch.dict("os.environ", ENV)
def test_fetch_dataset_oversized_truncated_to_fixed_count():
    big = [{"v": "x" * 700} for _ in range(2500)]
    assert len(json.dumps(big)) > data_client.MAX_SERIALIZED_BYTES
    with patch("sheetgo_agent.data_client.requests.get", return_value=_resp(200, big)):
        result = data_client.fetch_dataset("F", "sg_k")
    assert len(result) == data_client.TRUNCATED_RECORD_COUNT


@patch.dict("os.environ", ENV)
def test_search_files_uses_passed_api_key():
    hits = [{"id": "s1", "name": "Sales"}]
    with patch("sheetgo_agent.data_client.requests.get", return_value=_resp(200, hits)) as get:
        out = data_client.search_files("Sales", "sg_client_key")
    assert out == hits
    assert get.call_args[0][0] == "https://api.example.com/rest/beta/files/search"
    assert get.call_args[1]["params"] == {"q": "Sales"}
    assert get.call_args[1]["headers"]["Authorization"] == "Bearer sg_client_key"


@patch.dict("os.environ", ENV)
def test_search_files_non_200_raises():
    with patch("sheetgo_agent.data_client.requests.get", return_value=_resp(500, text="boom")):
        with pytest.raises(data_client.DataFetchError):
            data_client.search_files("x", "sg_k")
