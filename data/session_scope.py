"""Private Streamlit session storage; CLI callers retain local file storage."""

import os


def private_state():
    """Return session state when serving the app in private mode."""
    if os.environ.get("AGENT_LOCAL_PERSISTENCE") == "1":
        return None
    try:
        import streamlit as st
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx(suppress_warning=True) is not None:
            return st.session_state
    except (ImportError, RuntimeError):
        pass
    return None
