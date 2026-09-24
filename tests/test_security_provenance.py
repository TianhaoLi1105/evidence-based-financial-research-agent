"""Session isolation, HTML attributes, and source provenance regressions."""
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.getcwd())

from components.chat import _inline
from data import chat_store, storage, cache
from services import stock_service
from streamlit.testing.v1 import AppTest


# Two browser sessions cannot read each other's credentials or conversations.
first, second = {}, {}
with mock.patch.object(storage, "private_state", return_value=first), \
     mock.patch.object(chat_store, "private_state", return_value=first):
    storage.save_config({"api_key": "first-key"})
    sid = chat_store.create_session()["id"]
    chat_store.append_message(sid, {"role": "user", "content": "private"})
with mock.patch.object(storage, "private_state", return_value=second), \
     mock.patch.object(chat_store, "private_state", return_value=second):
    assert storage.load_config() == {}
    assert chat_store.list_sessions() == []
with mock.patch.object(storage, "private_state", return_value=first), \
     mock.patch.object(chat_store, "private_state", return_value=first):
    assert storage.load_config()["api_key"] == "first-key"
    assert chat_store.get_session(sid)["messages"][0]["content"] == "private"

# Real Streamlit script contexts use private session state by default.
old_mode = os.environ.pop("AGENT_LOCAL_PERSISTENCE", None)
try:
    script = """import streamlit as st
from data.storage import load_config, save_config
save_config({'api_key': st.session_state.get('key', 'alpha')})
st.write(load_config()['api_key'])
"""
    a = AppTest.from_string(script).run()
    b = AppTest.from_string(script).run()
    assert a.session_state["_agent_config"]["api_key"] == "alpha"
    b.session_state["key"] = "beta"
    b.run()
    assert b.session_state["_agent_config"]["api_key"] == "beta"
    assert a.session_state["_agent_config"]["api_key"] == "alpha"
finally:
    if old_mode is not None:
        os.environ["AGENT_LOCAL_PERSISTENCE"] = old_mode

# URL quote characters remain inside the href attribute.
html = _inline('[x](https://example.com"onmouseover="alert(1))')
assert 'onmouseover="' not in html
assert '&quot;' in html

# A cached price series retains the original data provider.
with tempfile.TemporaryDirectory() as tmp, mock.patch.object(cache, "CACHE_DIR", tmp):
    rows = [{"datetime": "2026-01-01", "close": "12"}]
    with mock.patch.object(stock_service, "get_time_series", return_value=rows):
        assert stock_service._time_series_with_fallback("TEST", 30)[1] == "twelvedata"
    cached = cache.get_cached_time_series_record("TEST", "1day", 30)
    assert cached["source"] == "twelvedata" and cached["ts"]
    assert stock_service._time_series_with_fallback("TEST", 30)[1] == "cache"

print("PASS security and provenance")
