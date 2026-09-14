#!/usr/bin/env python3
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>

"""
SwiftBar 插件: DeepSeek API 用量监控
数据来源: api.deepseek.com/user/balance（直接 API 调用，无需浏览器）
刷新频率: 10分钟（文件名中的 .10m.）

功能:
- 菜单栏显示当前余额
- 下拉菜单显示余额详情、今日/本月花费估算（基于余额变化记录）
- 本地 JSON 记录余额历史，仅在有变化时追加

安装:
1. 安装 SwiftBar: https://github.com/swiftbar/SwiftBar/releases
2. 配置 DeepSeek API Key（~/.kimi-code/config.toml 中 [providers.deepseek] 段）
3. 将本文件复制到 SwiftBar 插件目录:
   cp deepseek_usage.10m.py "$HOME/Library/Application Support/SwiftBar/plugins/"
4. 确保可执行: chmod +x "$HOME/Library/Application Support/SwiftBar/plugins/deepseek_usage.10m.py"
"""

import json
import os
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# 北京时间 (UTC+8)
BJT = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
CONFIG_PATH = os.path.expanduser("~/.kimi-code/config.toml")
BALANCE_URL = "https://api.deepseek.com/user/balance"

ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".archive")
BALANCE_LOG_PATH = os.path.join(ARCHIVE_DIR, "deepseek_balance_log.jsonl")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def get_api_key() -> str:
    """从 kimi-code config.toml 读取 DeepSeek API key（兼容 Python 3.9，不用 tomllib）。"""
    with open(CONFIG_PATH, "r") as f:
        content = f.read()
    # 匹配 [providers.deepseek] 节下的 api_key
    m = re.search(r'\[providers\.deepseek\].*?api_key\s*=\s*"([^"]+)"', content, re.DOTALL)
    if not m:
        raise ValueError("未在 config.toml 中找到 [providers.deepseek] api_key")
    return m.group(1)


def fetch_balance(api_key: str) -> float:
    """调用 api.deepseek.com/user/balance 获取当前余额（CNY）。"""
    req = urllib.request.Request(
        BALANCE_URL,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.load(resp)
    # 取 topped_up_balance（充值余额），CNY 货币
    for info in data.get("balance_infos", []):
        if info.get("currency") == "CNY":
            return float(info["topped_up_balance"])
    return 0.0


# ---------------------------------------------------------------------------
# 余额日志管理
# ---------------------------------------------------------------------------

def load_balance_log() -> list[dict]:
    """加载余额变化日志。"""
    if not os.path.exists(BALANCE_LOG_PATH):
        return []
    records = []
    with open(BALANCE_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def append_balance_log(balance: float) -> None:
    """仅在余额变化时追加一条记录。"""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    now = datetime.now(BJT)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    # 读上一条记录，余额相同则跳过
    prev_balance = None
    if os.path.exists(BALANCE_LOG_PATH):
        # 读最后一行
        with open(BALANCE_LOG_PATH, "rb") as f:
            f.seek(0, 2)  # EOF
            size = f.tell()
            if size > 0:
                # 从尾部往回找最后一行
                f.seek(max(0, size - 512))
                tail = f.read().decode("utf-8")
                lines = tail.strip().split("\n")
                if lines:
                    try:
                        prev = json.loads(lines[-1])
                        prev_balance = prev.get("balance")
                    except (json.JSONDecodeError, IndexError):
                        pass

    if prev_balance is not None and abs(balance - prev_balance) < 0.0001:
        return  # 余额没变，不记录

    with open(BALANCE_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now_str, "balance": balance}, ensure_ascii=False) + "\n")


def calc_spending(records: list[dict], since: datetime) -> float:
    """从日志记录中计算自 since 以来的总花费（余额减少量）。"""
    records_in_range = [r for r in records if r["ts"] >= since.strftime("%Y-%m-%d")]
    if len(records_in_range) < 2:
        return 0.0
    first = records_in_range[0]["balance"]
    last = records_in_range[-1]["balance"]
    spending = first - last
    return max(0.0, spending)


def get_daily_spending(records: list[dict]) -> list[tuple[str, float]]:
    """计算近 N 天每日花费，返回 [(label, amount), ...]"""
    now = datetime.now(BJT)
    today = now.strftime("%Y-%m-%d")
    result = []

    for days_ago in range(4, -1, -1):
        d = now - timedelta(days=days_ago)
        day_str = d.strftime("%Y-%m-%d")
        day_records = [r for r in records if r["ts"].startswith(day_str)]

        if day_str == today:
            label = "今天"
        elif day_str == (now - timedelta(days=1)).strftime("%Y-%m-%d"):
            label = "昨天"
        else:
            label = d.strftime("%m-%d")

        if len(day_records) >= 2:
            spent = day_records[0]["balance"] - day_records[-1]["balance"]
            result.append((label, max(0.0, spent)))
        else:
            result.append((label, 0.0))

    return result


# ---------------------------------------------------------------------------
# 格式化输出
# ---------------------------------------------------------------------------

def fmt_cny(val: float) -> str:
    return f"{val:.2f}"


def fmt_cny_small(val: float) -> str:
    return f"{val:.2f}"


def main():
    # 读取 API key
    try:
        api_key = get_api_key()
    except Exception as e:
        print("DS ? | refresh=true")
        print("---")
        print(f"⚠️ 无法读取 API Key | color=red")
        print(f"{e}")
        return

    if not api_key:
        print("DS ? | refresh=true")
        print("---")
        print("⚠️ DeepSeek API Key 未配置 | color=red")
        print("请在 ~/.kimi-code/config.toml 中设置 [providers.deepsearch] api_key")
        return

    # 获取余额
    try:
        balance = fetch_balance(api_key)
    except Exception as e:
        print("DS ? | refresh=true")
        print("---")
        print(f"❌ 获取余额失败 | color=red")
        print(f"{e}")
        return

    # 记录余额日志
    append_balance_log(balance)
    records = load_balance_log()

    # 计算花费
    now = datetime.now(BJT)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    today_spent = calc_spending(records, today_start)
    month_spent = calc_spending(records, month_start)
    seven_days_spent = calc_spending(records, now - timedelta(days=7))

    # 每日花费明细
    daily = get_daily_spending(records)

    # ---- 菜单栏标题：显示今日花费 ----
    print(f"{fmt_cny_small(today_spent)} | refresh=true size=10")
    print("---")

    # 花费汇总（无 emoji）
    print(f"M {fmt_cny(month_spent)} | font='Noto Sans CJK SC' size=9 refresh=true")
    print(f"7D {fmt_cny(seven_days_spent)} | font='Noto Sans CJK SC' size=9 refresh=true")
    print("---")

    # ---- 近5日每日花费（不折叠）----
    for label, spent in daily:
        if spent == 0:
            print(f"{label} 无花费 | font='Noto Sans Mono' size=9 color=#888888 refresh=true")
        else:
            print(f"{label} {fmt_cny_small(spent)} | font='Noto Sans Mono' size=9 refresh=true")
    print("---")

    print(f"{fmt_cny(balance)} | font='Noto Sans Mono' size=10 refresh=true")
    print("DeepSeek Platform | href=https://platform.deepseek.com/usage")
    print(f"刷新 | refresh=true terminal=false bash={__file__}")


if __name__ == "__main__":
    main()
