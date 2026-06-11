"""Shared pytest fixtures for sheetgo_agent unit tests.

Ensures the memcached client does not attempt a real connection during
import-time initialisation of cache.py (CacheController instantiates
memcache.Client at module load).  Setting a dummy MEMCACHED_URL before any
sheetgo_agent module is imported is sufficient — the python-memcached client
only opens a socket on the first actual get/set call.
"""
import os

# Guard: only set if absent so a real value coming from the environment is
# not overwritten when running against a live memcached instance.
os.environ.setdefault("MEMCACHED_URL", "localhost:11211")
