"""
Chat Session Store (V3.2.2a)
============================
AI 对话的本地持久化：把聊天记录保存到独立的 chat_history.json，
刷新页面 / 重启应用后不丢失；一次到位支持多个会话（话题），
供 3.2.2b 的多会话 UI 使用。

设计要点：
- 独立文件，不混入 .agent_config.json（避免配置膨胀与读写冲突）
- 原子写入（临时文件 + os.replace），崩溃也不会写坏
- 容量保护：单会话最多 MAX_MESSAGES 条，总会话数最多 MAX_SESSIONS
- 每次读写磁盘（Streamlit rerun 时模块会被重新导入，内存缓存无意义）
"""

import json
import os
import threading
import time
import uuid

# 项目根目录下的聊天记录文件
CHAT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "chat_history.json")

MAX_SESSIONS = 30      # 会话总数上限（超出自动淘汰最久未用的）
MAX_MESSAGES = 60      # 单会话消息条数上限（超出丢弃最早的）
DEFAULT_TITLE = "New Chat"

_LOCK = threading.Lock()


# ─── 底层读写（原子） ────────────────────────────────────

def _load() -> dict:
    """读取整个存储；文件缺失/损坏时返回空结构"""
    try:
        with open(CHAT_PATH, encoding="utf-8") as f:
            store = json.load(f)
        if isinstance(store, dict) and isinstance(store.get("sessions"), list):
            return store
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {"version": 1, "active_session_id": None, "sessions": []}


def _save(store: dict) -> None:
    """原子写入（先写临时文件再替换）"""
    tmp = CHAT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False)
    os.replace(tmp, CHAT_PATH)


# ─── 会话元数据 ──────────────────────────────────────────

def default_title(messages: list) -> str:
    """从第一条用户消息生成会话标题（截断为 20 字）"""
    for m in messages or []:
        if m.get("role") == "user":
            text = " ".join(str(m.get("content", "")).split())
            if not text:
                continue
            return (text[:20] + "…") if len(text) > 20 else text
    return DEFAULT_TITLE


def list_sessions() -> list:
    """返回所有会话的元数据（不含 messages），按最近使用排序"""
    store = _load()
    sessions = []
    for s in store["sessions"]:
        sessions.append({
            "id": s.get("id"),
            "title": s.get("title") or DEFAULT_TITLE,
            "created_at": s.get("created_at"),
            "updated_at": s.get("updated_at"),
            "message_count": len(s.get("messages") or []),
            "context": s.get("context"),
        })
    sessions.sort(key=lambda s: s.get("updated_at") or 0, reverse=True)
    return sessions


def get_session(session_id: str) -> dict:
    """返回单个会话（含 messages）；不存在返回 None"""
    if not session_id:
        return None
    for s in _load()["sessions"]:
        if s.get("id") == session_id:
            return s
    return None


def create_session(title: str = None, messages: list = None) -> dict:
    """新建会话并设为当前；超出会话数上限时淘汰最久未用的"""
    with _LOCK:
        store = _load()
        now = time.time()
        sess = {
            "id": uuid.uuid4().hex,
            "title": title or default_title(messages),
            "created_at": now,
            "updated_at": now,
            "context": None,   # V3.2.2c：话题主题快照（页面模式/股票/周期）
            "messages": (messages or [])[-MAX_MESSAGES:],
        }
        store["sessions"].append(sess)
        if len(store["sessions"]) > MAX_SESSIONS:
            # 淘汰最久未更新的会话（保留刚创建的这个）
            store["sessions"].sort(key=lambda s: s.get("updated_at") or 0)
            store["sessions"] = store["sessions"][-MAX_SESSIONS:]
        store["active_session_id"] = sess["id"]
        _save(store)
        return sess


def append_message(session_id: str, message: dict) -> dict:
    """向会话追加一条消息（自动裁剪与更新时间），返回更新后的会话"""
    if not session_id:
        return None
    with _LOCK:
        store = _load()
        for sess in store["sessions"]:
            if sess.get("id") == session_id:
                sess.setdefault("messages", []).append(message)
                sess["messages"] = sess["messages"][-MAX_MESSAGES:]
                # 首条用户消息自动生成会话标题（供后续话题列表展示）
                if (message.get("role") == "user"
                        and sess.get("title") in (None, "", DEFAULT_TITLE)):
                    title = default_title(sess["messages"])
                    if title != DEFAULT_TITLE:
                        sess["title"] = title
                sess["updated_at"] = time.time()
                _save(store)
                return sess
        return None


def clear_session(session_id: str) -> bool:
    """清空会话消息（保留会话本身）；标题重置为默认"""
    if not session_id:
        return False
    with _LOCK:
        store = _load()
        for sess in store["sessions"]:
            if sess.get("id") == session_id:
                sess["messages"] = []
                sess["title"] = DEFAULT_TITLE
                sess["updated_at"] = time.time()
                _save(store)
                return True
        return False


def set_session_context(session_id: str, context: dict) -> bool:
    """记录会话的主题快照（V3.2.2c：页面模式/股票/周期）"""
    if not session_id:
        return False
    with _LOCK:
        store = _load()
        for sess in store["sessions"]:
            if sess.get("id") == session_id:
                sess["context"] = context
                _save(store)
                return True
        return False


def get_session_context(session_id: str) -> dict:
    """读取会话主题快照；无则返回 None"""
    if not session_id:
        return None
    for s in _load()["sessions"]:
        if s.get("id") == session_id:
            return s.get("context")
    return None


def delete_session(session_id: str) -> bool:
    """删除会话；若删除的是当前会话，把 active 切到最近的一个"""
    if not session_id:
        return False
    with _LOCK:
        store = _load()
        before = len(store["sessions"])
        store["sessions"] = [s for s in store["sessions"] if s.get("id") != session_id]
        if len(store["sessions"]) == before:
            return False
        if store.get("active_session_id") == session_id:
            if store["sessions"]:
                store["sessions"].sort(key=lambda s: s.get("updated_at") or 0,
                                       reverse=True)
                store["active_session_id"] = store["sessions"][0]["id"]
            else:
                store["active_session_id"] = None
        _save(store)
        return True


# ─── 当前会话 ────────────────────────────────────────────

def get_active_session_id() -> str:
    """返回上次使用的会话 id（无则 None）"""
    return _load().get("active_session_id")


def set_active_session_id(session_id: str) -> None:
    """记录当前会话（供刷新后恢复）"""
    if not session_id:
        return
    with _LOCK:
        store = _load()
        if any(s.get("id") == session_id for s in store["sessions"]):
            store["active_session_id"] = session_id
            _save(store)
