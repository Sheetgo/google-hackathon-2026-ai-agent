# sheetgo_agent/data_client.py
"""Client for Core-API's file endpoints.

- fetch_dataset(file_id, api_key): GET /rest/beta/files/{id} -> list of record dicts.
- search_files(query, api_key):    GET /rest/beta/files/search -> list of {id, name}.
Authenticated with the caller-supplied Sheetgo API key.
"""
import json
import logging
import os

import requests

logger = logging.getLogger(__name__)

MAX_SERIALIZED_BYTES = int(1 * 1024 * 1024)  # 1 MB
TRUNCATED_RECORD_COUNT = 2000
REQUEST_TIMEOUT = 30


class DataFetchError(Exception):
    """Raised when Core-API returns a non-200 response."""


def _base_url():
    return os.environ["CORE_API_BASE_URL"].rstrip("/")


def fetch_dataset(file_id, api_key):
    """Return the file's first-tab data as a list of record dicts (truncated to
    TRUNCATED_RECORD_COUNT when over MAX_SERIALIZED_BYTES). Raises DataFetchError
    on a non-200 response."""
    url = f"{_base_url()}/rest/beta/files/{file_id}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=REQUEST_TIMEOUT)
    if resp.status_code != 200:
        raise DataFetchError(f"Core-API returned {resp.status_code} for {url}: {resp.text}")
    dataset = resp.json()
    if len(json.dumps(dataset)) > MAX_SERIALIZED_BYTES:
        logger.warning("Dataset exceeds %d bytes; truncating to first %d records",
                       MAX_SERIALIZED_BYTES, TRUNCATED_RECORD_COUNT)
        dataset = dataset[:TRUNCATED_RECORD_COUNT]
    return dataset


def search_files(query, api_key):
    """Search the user's Google Sheets by name -> list of {id, name}. Raises
    DataFetchError on a non-200 response."""
    url = f"{_base_url()}/rest/beta/files/search"
    resp = requests.get(url, headers={"Authorization": f"Bearer {api_key}"},
                        params={"q": query}, timeout=REQUEST_TIMEOUT)
    if resp.status_code != 200:
        raise DataFetchError(f"Core-API returned {resp.status_code} for {url}: {resp.text}")
    return resp.json()
