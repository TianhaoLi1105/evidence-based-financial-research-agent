"""
Utility Functions
=================
通用工具函数：数字格式化、安全类型转换。
"""


def format_large_num(val) -> str:
    """把大数字格式化为 T/B/M 缩写（如 2.5B、800M）"""
    if val is None:
        return "N/A"
    try:
        val = float(val)
        if abs(val) >= 1e12:
            return f"${val/1e12:.2f}T"
        elif abs(val) >= 1e9:
            return f"${val/1e9:.2f}B"
        elif abs(val) >= 1e6:
            return f"${val/1e6:.2f}M"
        else:
            return f"${val:,.0f}"
    except (ValueError, TypeError):
        return str(val)


def safe_float(val, default=None):
    """安全转换为 float，失败时返回默认值"""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default
