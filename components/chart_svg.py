"""
Chat Chart SVG (V3.3.2)
=======================
对话内出图：把价格数据渲染成 Apple 深色风格的 SVG 图表，
以 HTML 字符串形式嵌入聊天消息区（#chat-msgs 浮层）。

纯函数实现，不依赖 plotly/streamlit，可独立单元测试。
颜色约定与页面图表一致：绿涨 #34c759 / 红跌 #ff3b30 / 主蓝 #0a84ff。
"""

import math

# ─── 色板（与 services/app_state.py 的 C 一致）───
BLUE = "#0a84ff"
GREEN = "#34c759"
RED = "#ff3b30"
GRID = "#2c2c2e"
AXIS = "#6e6e73"
TEXT = "#f5f5f7"
MUTED = "#98989d"
MULTI_COLORS = (BLUE, "#af52de", "#ff9f0a", GREEN, RED)

W = 420  # viewBox 宽（消息区 428px 减去内边距）
PAD_L, PAD_R, PAD_T, PAD_B = 8, 8, 14, 26


def _f(v):
    """安全转 float"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _num(s):
    """紧凑数字格式化：12345 → 12.3K"""
    if s is None:
        return "-"
    if abs(s) >= 1e12:
        return f"{s / 1e12:.2f}T"
    if abs(s) >= 1e9:
        return f"{s / 1e9:.2f}B"
    if abs(s) >= 1e6:
        return f"{s / 1e6:.1f}M"
    if abs(s) >= 1e3:
        return f"{s / 1e3:.1f}K"
    return f"{s:.2f}"


def _grid_lines(vmin, vmax, n=4):
    """生成 (value, y) 网格参考线（含边界）"""
    if vmin == vmax:
        vmax = vmin + 1
    step = (vmax - vmin) / n
    return [(vmin + step * i) for i in range(n + 1)]


def _svg_open(h):
    return (f'<svg viewBox="0 0 {W} {h}" width="100%" height="auto" '
            f'style="display:block;border-radius:10px;'
            f'background:rgba(44,44,46,.35);border:1px solid {GRID}" '
            f'xmlns="http://www.w3.org/2000/svg" role="img">')


def _svg_close():
    return "</svg>"


def _price_scale(vmin, vmax, plot_h):
    if vmin == vmax:
        vmax = vmin + 1
    def y_of(v):
        return PAD_T + (vmax - v) / (vmax - vmin) * plot_h
    return y_of


def price_line_svg(rows, height=200, ticker=""):
    """收盘价折线图（面积渐变 + 网格 + 收盘标注），涨跌着色"""
    closes = [_f(r.get("close")) for r in rows]
    valid = [c for c in closes if c is not None]
    if len(valid) < 2:
        return ""
    plot_h = height - PAD_T - PAD_B
    vmin, vmax = min(valid), max(valid)
    pad = (vmax - vmin) * 0.08 or max(abs(vmax) * 0.01, 0.01)
    vmin, vmax = vmin - pad, vmax + pad
    y_of = _price_scale(vmin, vmax, plot_h)

    n = len(closes)
    pts = []
    for i, c in enumerate(closes):
        if c is None:
            continue
        x = PAD_L + (i / (n - 1)) * (W - PAD_L - PAD_R)
        pts.append(f"{x:.1f},{y_of(c):.1f}")
    poly = " ".join(pts)
    up = closes[-1] >= closes[0]
    color = GREEN if up else RED

    grid = ""
    labels = []
    for v in _grid_lines(vmin, vmax, 3):
        y = y_of(v)
        grid += f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>'
        labels.append(f'<text x="{W - PAD_R - 4}" y="{y - 4:.1f}" text-anchor="end" '
                      f'font-size="9" fill="{AXIS}">{_num(v)}</text>')

    first_x = PAD_L
    last_x = W - PAD_R
    last_c = closes[-1]
    x_dates = [r.get("datetime") for r in rows]
    date_first = str(x_dates[0] or "")[:10]
    date_last = str(x_dates[-1] or "")[:10]

    return (_svg_open(height)
            + grid
            + "".join(labels)
            + f'<defs><linearGradient id="gfill" x1="0" y1="0" x2="0" y2="1">'
              f'<stop offset="0%" stop-color="{color}" stop-opacity=".18"/>'
              f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/>'
              f'</linearGradient></defs>'
            + f'<polygon points="{PAD_L},{y_of(closes[0]):.1f} {poly} '
              f'{W - PAD_R},{y_of(closes[0]):.1f}" fill="url(#gfill)"/>'
            + f'<polyline points="{poly}" fill="none" stroke="{color}" '
              f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
            + f'<circle cx="{last_x:.1f}" cy="{y_of(last_c):.1f}" r="3" fill="{color}"/>'
            + f'<text x="{first_x}" y="{height - 8}" font-size="9" fill="{AXIS}">{date_first}</text>'
            + f'<text x="{last_x}" y="{height - 8}" text-anchor="end" font-size="9" fill="{AXIS}">{date_last}</text>'
            + f'<text x="{W - PAD_R}" y="{PAD_T + 2}" text-anchor="end" font-size="11" '
              f'font-weight="600" fill="{TEXT}">{_num(last_c)}</text>'
            + _svg_close())


def candlestick_svg(rows, height=220):
    """K 线蜡烛图 + 底部成交量小柱"""
    bars = []
    for r in rows:
        o, h, l, c = (_f(r.get(k)) for k in ("open", "high", "low", "close"))
        if None in (o, h, l, c):
            continue
        bars.append({"o": o, "h": h, "l": l, "c": c,
                     "v": _f(r.get("volume"))})
    if len(bars) < 2:
        return ""
    vol_h = 34
    plot_h = height - PAD_T - PAD_B - vol_h - 6
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]
    vmin, vmax = min(lows), max(highs)
    pad = (vmax - vmin) * 0.06 or max(abs(vmax) * 0.01, 0.01)
    vmin, vmax = vmin - pad, vmax + pad
    y_of = _price_scale(vmin, vmax, plot_h)

    vols = [b["v"] or 0 for b in bars]
    vmax_v = max(vols) or 1
    n = len(bars)
    bw = (W - PAD_L - PAD_R) / n
    cw = max(bw * 0.55, 1.0)

    cells = []
    for i, b in enumerate(bars):
        x = PAD_L + i * bw + bw / 2
        up = b["c"] >= b["o"]
        color = GREEN if up else RED
        body_top = y_of(max(b["o"], b["c"]))
        body_h = max(abs(y_of(b["o"]) - y_of(b["c"])), 1.0)
        cells.append(f'<line x1="{x:.2f}" y1="{y_of(b["h"]):.1f}" '
                     f'x2="{x:.2f}" y2="{y_of(b["l"]):.1f}" stroke="{color}" stroke-width="1"/>')
        cells.append(f'<rect x="{x - cw / 2:.2f}" y="{body_top:.1f}" width="{cw:.2f}" '
                     f'height="{body_h:.1f}" fill="{color}" rx="0.5"/>')
        # 成交量小柱（底部）
        vh = max((b["v"] or 0) / vmax_v * vol_h, 0.8)
        cells.append(f'<rect x="{x - cw / 2:.2f}" y="{PAD_T + plot_h + 6 + vol_h - vh:.1f}" '
                     f'width="{cw:.2f}" height="{vh:.1f}" fill="{color}" opacity=".4" rx="0.5"/>')

    grid = ""
    labels = []
    for v in _grid_lines(vmin, vmax, 3):
        y = y_of(v)
        grid += f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>'
        labels.append(f'<text x="{W - PAD_R - 4}" y="{y - 4:.1f}" text-anchor="end" '
                      f'font-size="9" fill="{AXIS}">{_num(v)}</text>')
    date_first = str(rows[0].get("datetime") or "")[:10]
    date_last = str(rows[-1].get("datetime") or "")[:10]

    return (_svg_open(height)
            + grid + "".join(labels) + "".join(cells)
            + f'<text x="{PAD_L}" y="{height - 8}" font-size="9" fill="{AXIS}">{date_first}</text>'
            + f'<text x="{W - PAD_R}" y="{height - 8}" text-anchor="end" font-size="9" fill="{AXIS}">{date_last}</text>'
            + _svg_close())


def multi_line_svg(histories, height=200):
    """多股归一化走势对比（起点 = 100），带图例与期末涨跌"""
    series = []
    for tk, rows in (histories or {}).items():
        closes = [_f(r.get("close")) for r in rows]
        valid = [c for c in closes if c is not None and c != 0]
        if len(valid) < 2:
            continue
        base = valid[0]
        series.append((str(tk).upper(), [c / base * 100 for c in valid]))
    if not series:
        return ""
    # 图例每行最多 3 项，超过自动换行（避免 4-5 只股票时溢出 viewBox）
    legend_rows = (len(series) + 2) // 3
    legend_h = 8 + legend_rows * 12
    plot_h = height - PAD_T - PAD_B - legend_h
    all_vals = [v for _, vs in series for v in vs]
    vmin, vmax = min(all_vals), max(all_vals)
    pad = (vmax - vmin) * 0.12 or 5
    vmin, vmax = vmin - pad, vmax + pad
    y_of = _price_scale(vmin, vmax, plot_h)

    grid = ""
    labels = []
    for v in _grid_lines(vmin, vmax, 3):
        y = y_of(v)
        grid += f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>'
        labels.append(f'<text x="{W - PAD_R - 4}" y="{y - 4:.1f}" text-anchor="end" '
                      f'font-size="9" fill="{AXIS}">{v:.0f}</text>')

    traces = ""
    legend = ""
    max_n = max(len(vs) for _, vs in series)
    for idx, (tk, vs) in enumerate(series):
        color = MULTI_COLORS[idx % len(MULTI_COLORS)]
        pts = []
        for i, v in enumerate(vs):
            x = PAD_L + (i / (max_n - 1)) * (W - PAD_L - PAD_R)
            pts.append(f"{x:.1f},{y_of(v):.1f}")
        traces += (f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" '
                   f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
        chg = vs[-1] - 100
        col, row = idx % 3, idx // 3
        lx = PAD_L + col * 138
        ly = PAD_T + plot_h + 8 + row * 12
        legend += (f'<rect x="{lx}" y="{ly}" width="8" height="8" rx="2" fill="{color}"/>'
                   f'<text x="{lx + 12}" y="{ly + 8}" font-size="9" '
                   f'fill="{MUTED}">{tk} {chg:+.1f}%</text>')
    return (_svg_open(height)
            + grid + "".join(labels) + traces + legend
            + _svg_close())
