#!/usr/bin/env python3
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>

"""
SwiftBar / xbar 插件: Kimi Code 用量监控
安装:
1. 安装 SwiftBar: https://github.com/swiftbar/SwiftBar/releases
2. 将本文件复制到 SwiftBar 插件目录:
   cp kimi_usage.2m.py "$HOME/Library/Application Support/SwiftBar/plugins/"
3. 确保文件可执行: chmod +x "$HOME/Library/Application Support/SwiftBar/plugins/kimi_usage.2m.py"
4. SwiftBar 会自动识别并显示在菜单栏

刷新频率: 2分钟 (文件名中的 .2m. 控制)
"""

import json
import os
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

CREDENTIALS_PATH = os.path.expanduser("~/.kimi-code/credentials/kimi-code.json")
USAGE_URL = "https://api.kimi.com/coding/v1/usages"


def get_access_token() -> str:
    with open(CREDENTIALS_PATH, "r") as f:
        data = json.load(f)
    return data["access_token"]


def fetch_usage(max_retries=3, base_delay=1.0, allow_refresh=True):
    token = get_access_token()
    req = urllib.request.Request(
        USAGE_URL,
        headers={"Authorization": f"Bearer {token}"},
    )

    last_exception = None
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            last_exception = e
            # 401 可能是 token 过期，尝试运行 kimi 刷新 session
            if e.code == 401 and allow_refresh:
                try:
                    # 运行 kimi 命令触发登录流程刷新 token，设置超时避免长时间等待
                    subprocess.run(
                        [os.path.expanduser("~/.kimi-code/bin/kimi")],
                        capture_output=True,
                        timeout=15
                    )
                    # 重新读取 token
                    token = get_access_token()
                    req = urllib.request.Request(
                        USAGE_URL,
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    # 不再允许刷新，避免无限循环
                    allow_refresh = False
                    continue
                except Exception:
                    pass
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
            else:
                raise last_exception
        except (urllib.error.URLError, TimeoutError) as e:
            last_exception = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
            else:
                raise last_exception
        except Exception:
            raise


def format_reset_time(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = dt - now
        seconds = int(delta.total_seconds())
        if seconds <= 0:
            return "即将重置"
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        mins = (seconds % 3600) // 60
        secs = seconds % 60
        parts = []
        if days:
            parts.append(f"{days}D ")
        if hours and days < 1:
            parts.append(f"{hours}H ")
        if hours and days >= 1:
            parts.append(f"{(hours + mins/60):.1f}H ")
        if mins and days < 1:
            parts.append(f"{mins}M")
        if secs and not parts:
            parts.append(f"{secs}S")
        return "".join(parts)
    except Exception:
        return iso_str


def ratio_color(ratio: float) -> str:
    if ratio >= 0.9:
        return "🔴"
    if ratio >= 0.7:
        return "🟡"
    return "🟢"


def main():
    try:
        data = fetch_usage()
    except Exception as e:
        print("Kimi | refresh=true")
        print("---")
        print(f"获取失败: {e}")
        return

    usage = data.get("usage", {})
    limit = int(usage.get("limit", 0) or 0)
    used = int(usage.get("used", 0) or 0)
    remaining = int(usage.get("remaining", 0) or 0)
    reset_time = usage.get("resetTime", "")

    ratio = remaining / limit if limit > 0 else 0
    color = ratio_color(ratio)

    # 提取 300 分钟限额
    min300_used = 0
    min300_limit = 0
    min300_reset = ""
    limits = data.get("limits", [])
    for item in limits:
        detail = item.get("detail", item)
        window = item.get("window", {})
        duration = window.get("duration", "")
        time_unit = window.get("timeUnit", "")
        if str(duration) == "300" and "MINUTE" in time_unit:
            min300_used = int(detail.get("used", 0) or 0)
            min300_limit = int(detail.get("limit", 0) or 0)
            min300_reset = detail.get("resetTime", "")
            break

    # 菜单栏标题 (简洁显示)
    w_ratio = used / limit if limit > 0 else 0
    h_ratio = min300_used / min300_limit if min300_limit > 0 else 0

    w_display = format_reset_time(reset_time) if w_ratio >= 1 else f"{w_ratio:.0%}"
    h_display = format_reset_time(min300_reset) if h_ratio >= 1 else f"{h_ratio:.0%}"

    # 线性配额差值：按本周已过去比例计算预期用量，与实际用量对比
    diff_display = ""
    if reset_time and limit > 0:
        try:
            reset_dt = datetime.fromisoformat(reset_time.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            start_dt = reset_dt - timedelta(days=7)
            elapsed = (now - start_dt).total_seconds()
            total = 7 * 86400
            if elapsed > 0:
                elapsed = min(elapsed, total)
                expected = limit * (elapsed / total)
                diff = used - expected
                diff_display = f"{diff:+.0f}"
        except Exception:
            pass

    # 5小时限额差值
    min300_diff_display = ""
    if min300_reset and min300_limit > 0:
        try:
            reset_dt = datetime.fromisoformat(min300_reset.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            start_dt = reset_dt - timedelta(minutes=300)
            elapsed = (now - start_dt).total_seconds()
            total = 300 * 60
            if elapsed > 0:
                elapsed = min(elapsed, total)
                expected = min300_limit * (elapsed / total)
                diff = min300_used - expected
                min300_diff_display = f"{diff:+.0f}%"
        except Exception:
            pass

    title = f"W {w_display} H {h_display}"
    if diff_display:
        title += f" {diff_display}%"
    print(f"{title} | refresh=true size=13")
    print("---")

    # 下拉菜单详情
    if reset_time:
        print(f"{format_reset_time(reset_time)} | refresh=true font=Menlo size=13")
    if min300_reset:
        h_disp = format_reset_time(min300_reset)
        if min300_diff_display:
            h_disp += f" {min300_diff_display}"
        print(f"{h_disp} | refresh=true font=Menlo size=13")
    print("---")

    print("Kimi Console | href=https://www.kimi.com/code/console")
    print("Beta | href=https://www.kimi.com/code/beta")


if __name__ == "__main__":
    main()
