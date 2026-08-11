"""
Local Config Storage
====================
本地配置持久化：负责读写 .agent_config.json（API Key、自选股、AI 模型配置等）。
"""

import json
import os
import uuid

# 项目根目录下的配置文件
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".agent_config.json")


def load_config() -> dict:
    """读取本地配置，文件不存在或损坏时返回空字典"""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(data: dict) -> None:
    """合并保存配置到本地 JSON 文件（保留已有字段）"""
    merged = load_config()
    merged.update(data)
    with open(CONFIG_PATH, "w") as f:
        json.dump(merged, f)


# ─── AI 模型配置（V3 智能问答）────────────────────────────
def get_llm_profiles() -> list:
    """读取已保存的 AI 模型配置列表"""
    return load_config().get("llm_profiles", [])


def save_llm_profiles(profiles: list) -> None:
    """整体保存 AI 模型配置列表"""
    save_config({"llm_profiles": profiles})


def get_active_llm_profile_id() -> str:
    """读取当前使用的模型配置 id"""
    return load_config().get("llm_active_profile_id", "")


def set_active_llm_profile_id(pid: str) -> None:
    """设置当前使用的模型配置 id"""
    save_config({"llm_active_profile_id": pid})


def upsert_llm_profile(profile: dict) -> list:
    """
    新增或覆盖模型配置（同名覆盖，保留原 id），返回最新列表。
    """
    profiles = get_llm_profiles()
    name = (profile.get("name") or "").strip()
    for i, p in enumerate(profiles):
        if p.get("name") == name:
            profile["id"] = p.get("id") or uuid.uuid4().hex[:10]
            profiles[i] = profile
            break
    else:
        profile["id"] = uuid.uuid4().hex[:10]
        profiles.append(profile)
    save_llm_profiles(profiles)
    return profiles


def delete_llm_profile(pid: str) -> list:
    """按 id 删除模型配置；若删除的是当前使用项则清空当前 id。"""
    profiles = [p for p in get_llm_profiles() if p.get("id") != pid]
    save_llm_profiles(profiles)
    if get_active_llm_profile_id() == pid:
        set_active_llm_profile_id("")
    return profiles
