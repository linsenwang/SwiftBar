#!/usr/bin/env python3
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>

"""
SwiftBar 插件: Clash 状态监控（9090 端口）
刷新频率: 1 分钟（文件名中的 .1m. 控制）

功能:
- 菜单栏显示当前代理节点的国旗/地区旗和延迟（直连时显示「🌐 直连」）
- 点击标题立即刷新
- 下拉菜单显示实时上下行速率/总量、当前模式、已选地区组
- 支持在指定 Selector 组内一键切换地区/线路（含直连，直接平铺展示，不折叠）

性能:
- 节点延迟优先取 clash 自己维护的 history，不再每次刷新都对全部成员发 /delay 实测
- 仅对当前节点做一次实测，并与 /traffic 采样并行执行
- /traffic 只读首帧（mihomo 建连后立刻推一帧），不再空等采样窗口

配置环境变量（可选）:
- CLASH_HOST: 默认 127.0.0.1:9090
- CLASH_SECRET: 鉴权密钥；留空时自动从 ~/.config/clash/config.yaml 读取
- CLASH_GROUP: 用于切换地区组的 Selector 名称，默认 PROXY
"""

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

# -----------------------------------------------------------------------------
# 配置
# -----------------------------------------------------------------------------
SCRIPT_PATH = Path(__file__).resolve()
CLASH_HOST = os.environ.get("CLASH_HOST", "127.0.0.1:9090")
CLASH_SECRET = os.environ.get("CLASH_SECRET", "")
CLASH_GROUP = os.environ.get("CLASH_GROUP", "PROXY")
CONFIG_PATH = os.path.expanduser("~/.config/clash/config.yaml")

BASE_URL = f"http://{CLASH_HOST}"

# 从节点名称里过滤掉显然不是可切换代理的占位项
SKIP_KEYWORDS = ("剩余流量", "距离下次重置", "套餐到期", "下载新版", "官网：")


# -----------------------------------------------------------------------------
# 工具函数
# -----------------------------------------------------------------------------
def load_secret() -> str:
    """优先用环境变量，否则尝试读取 clash 配置文件里的 secret。"""
    if CLASH_SECRET:
        return CLASH_SECRET
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r'^secret:\s*(["\']?)(\S+)\1', line)
                if m:
                    return m.group(2).strip('"\'')
    except Exception:
        pass
    return ""


def auth_headers(secret: str) -> dict:
    h = {"Content-Type": "application/json"}
    if secret:
        h["Authorization"] = f"Bearer {secret}"
    return h


def api_call(path: str, method: str = "GET", data: Optional[dict] = None, secret: str = "") -> Optional[dict]:
    """调用 Clash REST API，返回 JSON 对象；空响应视为 {}；出错返回 None。"""
    url = BASE_URL + path
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, method=method, headers=auth_headers(secret))
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def proxy_delay(name: str, secret: str, timeout_ms: int = 3000) -> Optional[int]:
    """调用 /proxies/{name}/delay 测一次延迟。"""
    enc = urllib.parse.quote(name, safe="")
    path = f"/proxies/{enc}/delay?timeout={timeout_ms}&url=http://www.gstatic.com/generate_204"
    result = api_call(path, secret=secret)
    if result and "delay" in result:
        return int(result["delay"])
    return None


def last_history_delay(proxy_info: dict) -> Optional[int]:
    history = proxy_info.get("history", [])
    if history:
        return int(history[-1].get("delay", 0)) or None
    return None


def extract_flag(text: str) -> str:
    """从文本开头提取国旗/地区旗 emoji；没有则返回地球图标。"""
    if not text:
        return "🌐"
    m = re.search(r"[\U0001F1E6-\U0001F1FF]{2}", text)
    return m.group(0) if m else "🌐"


def display_name(name: str) -> str:
    """内置节点名换成更好读的中文。"""
    return {"DIRECT": "直连"}.get(name, name)


def is_direct(name: str, info: dict) -> bool:
    """判断成员是否为直连（节点名叫 DIRECT，或类型为 Direct）。"""
    return name == "DIRECT" or info.get("type") == "Direct"


def latency_color(ms: Optional[int]) -> str:
    if ms is None:
        return "#888888"
    if ms < 200:
        return "#34C759"
    if ms < 500:
        return "#FFCC00"
    return "#FF3B30"


def format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


def format_speed(n: int) -> str:
    s = format_bytes(n)
    return f"{s}/s"


def escape_swiftbar(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def sample_traffic(secret: str, timeout: float = 3.0) -> dict:
    """读 /traffic SSE 首帧，返回速率与总量（mihomo 建连后会立刻推一帧）。"""
    url = f"{BASE_URL}/traffic"
    req = urllib.request.Request(url, headers=auth_headers(secret))
    last_event = {"up": 0, "down": 0, "upTotal": 0, "downTotal": 0}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line.startswith("{"):
                    continue
                try:
                    last_event.update(json.loads(line))
                    break  # 首帧就是当前速率，不必再等下一帧
                except Exception:
                    pass
    except Exception:
        pass
    return last_event


def switch_selection(group: str, node: str, secret: str) -> bool:
    """把 Selector 切换到指定节点。"""
    enc = urllib.parse.quote(group, safe="")
    path = f"/proxies/{enc}"
    return api_call(path, method="PUT", data={"name": node}, secret=secret) is not None


def encode_node(name: str) -> str:
    return base64.urlsafe_b64encode(name.encode("utf-8")).decode("ascii")


def decode_node(b64: str) -> str:
    return base64.urlsafe_b64decode(b64.encode("ascii")).decode("utf-8")


# -----------------------------------------------------------------------------
# 主逻辑
# -----------------------------------------------------------------------------
def main():
    secret = load_secret()

    # 1) 基础连通性
    configs = api_call("/configs", secret=secret)
    proxies = api_call("/proxies", secret=secret)
    if configs is None or proxies is None:
        print("Clash | refresh=true size=13")
        # print("Clash | refresh=true size=13 color=red")
        print("---")
        print(f"无法连接 {CLASH_HOST} | color=red refresh=true")
        return

    proxy_map = proxies.get("proxies", {})
    group_info = proxy_map.get(CLASH_GROUP)
    if not group_info or group_info.get("type") != "Selector":
        print(f"🌐 {CLASH_GROUP}? | refresh=true size=13 color=#888888")
        print("---")
        print(f"未找到 Selector 组: {CLASH_GROUP} | color=red refresh=true")
        return

    current = group_info.get("now", "")
    current_info = proxy_map.get(current, {})
    on_direct = is_direct(current, current_info)

    # 2) 流量采样与当前节点测速互不依赖，并行执行省掉约 1 秒等待
    with ThreadPoolExecutor(max_workers=2) as pool:
        traffic_future = pool.submit(sample_traffic, secret)
        delay_future = None if on_direct else pool.submit(proxy_delay, current, secret)
        traffic = traffic_future.result()
        live_delay = delay_future.result() if delay_future else None

    delay = live_delay if live_delay is not None else last_history_delay(current_info)

    # 3) 标题：国旗 + 延迟；直连不测速，直接标出来
    flag = extract_flag(current)
    delay_text = f"{delay}ms" if delay is not None else "-"
    if on_direct:
        print(f"{flag} {display_name(current)} | font='Sarasa Mono SC' refresh=true size=13")
    else:
        print(f"{flag} {delay_text} | font='Sarasa Mono SC' refresh=true size=13")
    print("---")

    # 4) 实时速率
    mode = configs.get("mode", "unknown").upper()
    mixed_port = configs.get("mixed-port", 0)

    print(f"模式: {mode} | font='Sarasa Mono SC' size=13 refresh=true")
    if mixed_port:
        print(f"端口: {mixed_port} | font='Sarasa Mono SC' size=13 refresh=true")
    print(f"⬇ {format_speed(traffic.get('down', 0))}  ⬆ {format_speed(traffic.get('up', 0))} | font='Sarasa Mono SC' size=13 refresh=true")
    print(f"下行总计: {format_bytes(traffic.get('downTotal', 0))}  上行总计: {format_bytes(traffic.get('upTotal', 0))} | font='Sarasa Mono SC' size=12 color=#888888 refresh=true")
    print("---")

    # 5) 当前地区组
    current_label = escape_swiftbar(display_name(current) or "-")
    print(f"当前: {current_label} | font='Sarasa Mono SC' size=13 refresh=true")
    print("---")

    # 6) 可切换成员（平铺展示，不折叠；含直连）
    print("切换地区组 | font='Sarasa Mono SC' size=13 color=#888888 refresh=true")
    for member in group_info.get("all", []):
        if member == "REJECT":
            continue
        if any(kw in member for kw in SKIP_KEYWORDS):
            continue
        member_info = proxy_map.get(member, {})
        if member_info.get("type") == "Reject":
            continue

        is_current = member == current
        direct = is_direct(member, member_info)
        marker = "● " if is_current else ""

        if direct:
            # 直连不测速，也就没有延迟可言
            mdelay = None
            label = f"{marker}🌐 {display_name(member)}".strip()
        elif is_current:
            mdelay = delay  # 复用标题那次实测结果
        else:
            # 优先用 clash 自己维护的 history，避免每次刷新都实测一遍
            mdelay = last_history_delay(member_info)
            if mdelay is None:
                mdelay = proxy_delay(member, secret)

        if not direct:
            name_clean = re.sub(r"[\U0001F1E6-\U0001F1FF]{2}", "", member).strip()
            delay_part = f"{mdelay}ms" if mdelay is not None else "-"
            label = f"{marker}{extract_flag(member)} {name_clean} ({delay_part})".strip()

        color = latency_color(mdelay)

        if is_current:
            line = f"{label} | font='Sarasa Mono SC' size=13 color={color} refresh=true"
        else:
            b64 = encode_node(member)
            line = (
                f"{label} | bash={sys.executable} "
                f"param1={SCRIPT_PATH} param2=--switch param3={b64} "
                f"terminal=false refresh=true color={color}"
            )
        print(line)

    print("---")
    print(f"刷新 | refresh=true terminal=false bash={sys.executable} param1={SCRIPT_PATH}")
    print(f"Clash Dashboard | href=http://{CLASH_HOST}/ui#/")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--switch":
        target = decode_node(sys.argv[2])
        ok = switch_selection(CLASH_GROUP, target, load_secret())
        if not ok:
            print(f"切换失败: {target}", file=sys.stderr)
            sys.exit(1)
    else:
        main()
