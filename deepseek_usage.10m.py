#!/usr/bin/env python3
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>

"""
SwiftBar 插件: DeepSeek + OpenRouter API 用量监控
数据来源:
- DeepSeek: api.deepseek.com/user/balance（直接 API 调用，无需浏览器）
- OpenRouter: openrouter.ai/api/v1/credits（账户余额，需 OPENROUTER_MANAGEMENT_KEY）
刷新频率: 10分钟（文件名中的 .10m.）

功能:
- 菜单栏显示 DeepSeek + OpenRouter 今日花费合计（单个数字，均为人民币）
- 下拉菜单用 D / R 前缀区分两家，D 与 R 同一行显示: 月度、7日、每日花费、余额
- 两家完全同思路: 记余额（D 充值余额 / R 剩余 credits），每日花费 = 余额差分
  （余额下降量累加，充值不抵消），日志用北京时间时间戳
- OpenRouter 数值单位为 USD（1 credit = $1），按固定汇率 USD_CNY_RATE 换算为 CNY

安装:
1. 安装 SwiftBar: https://github.com/swiftbar/SwiftBar/releases
2. 配置 DeepSeek API Key（~/.kimi-code/config.toml 中 [providers.deepseek] 段）
3. 配置 OpenRouter Management Key（环境变量 OPENROUTER_MANAGEMENT_KEY，/credits 需要）:
   - 本机 key 定义在 ~/.keys（.zshrc 中 source ~/.keys）
   - 已安装 LaunchAgent ~/Library/LaunchAgents/local.openrouter-env.plist，
     登录时自动提取并 launchctl setenv（GUI 应用不继承 shell 环境变量，故需此步骤）
4. 将本文件复制到 SwiftBar 插件目录:
   cp deepseek_usage.10m.py "$HOME/Library/Application Support/SwiftBar/plugins/"
5. 确保可执行: chmod +x "$HOME/Library/Application Support/SwiftBar/plugins/deepseek_usage.10m.py"
"""

import json
import os
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from typing import Optional

# 北京时间 (UTC+8)
BJT = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
CONFIG_PATH = os.path.expanduser("~/.kimi-code/config.toml")
BALANCE_URL = "https://api.deepseek.com/user/balance"
OR_CREDITS_URL = "https://openrouter.ai/api/v1/credits"

USD_CNY_RATE = 6.76  # 固定 USD→CNY 汇率（OpenRouter 单位是 USD）

ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".archive")
BALANCE_LOG_PATH = os.path.join(ARCHIVE_DIR, "deepseek_balance_log.jsonl")
OR_BALANCE_LOG_PATH = os.path.join(ARCHIVE_DIR, "openrouter_balance_log.jsonl")


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


def get_or_mgmt_key() -> str:
    """从环境变量 OPENROUTER_MANAGEMENT_KEY 读取 OpenRouter management key（/credits 需要）。"""
    return os.environ.get("OPENROUTER_MANAGEMENT_KEY", "").strip()


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


def fetch_or_balance(mgmt_key: str) -> tuple[float, float]:
    """调用 openrouter.ai/api/v1/credits 获取账户余额（USD）。

    返回 (total_credits, total_usage)，剩余 = total_credits - total_usage。
    """
    req = urllib.request.Request(
        OR_CREDITS_URL,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {mgmt_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.load(resp)
    d = data.get("data", {}) or {}
    return float(d.get("total_credits") or 0.0), float(d.get("total_usage") or 0.0)


# ---------------------------------------------------------------------------
# 余额日志管理（D / R 共用: 记余额，每日花费 = 余额差分）
# ---------------------------------------------------------------------------

def load_balance_log(path: str) -> list[dict]:
    """加载余额变化日志。"""
    if not os.path.exists(path):
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def load_last_balance(path: str) -> Optional[float]:
    """从余额日志读取最近一次余额，作为接口失败时的缓存回退。"""
    records = load_balance_log(path)
    if not records:
        return None
    return records[-1]["balance"]


def append_balance_log(path: str, balance: float) -> None:
    """仅在余额变化时追加一条记录。"""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    now = datetime.now(BJT)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    # 读上一条记录，余额相同则跳过
    prev_balance = None
    if os.path.exists(path):
        # 读最后一行
        with open(path, "rb") as f:
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

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now_str, "balance": balance}, ensure_ascii=False) + "\n")


def calc_spending(records: list[dict], since: datetime) -> float:
    """从日志记录中计算自 since 以来的总花费（余额减少量）。

    逐段累加余额下降，遇到充值（余额上升）时不抵消，避免月度/今日花费被充值抹成 0。
    """
    records_in_range = [r for r in records if r["ts"] >= since.strftime("%Y-%m-%d")]
    if len(records_in_range) < 2:
        return 0.0

    spending = 0.0
    for prev, curr in zip(records_in_range, records_in_range[1:]):
        drop = prev["balance"] - curr["balance"]
        if drop > 0:
            spending += drop
    return spending


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
            label = "今天 "
        elif day_str == (now - timedelta(days=1)).strftime("%Y-%m-%d"):
            label = "昨天 "
        else:
            label = d.strftime("%m-%d")

        if len(day_records) >= 2:
            spent = 0.0
            for prev, curr in zip(day_records, day_records[1:]):
                drop = prev["balance"] - curr["balance"]
                if drop > 0:
                    spent += drop
            result.append((label, spent))
        else:
            result.append((label, 0.0))

    return result


# ---------------------------------------------------------------------------
# 格式化输出
# ---------------------------------------------------------------------------

def fmt2(val: float) -> str:
    return f"{val:.2f}"


def main():
    errors = []

    # ---- DeepSeek（key 来自 config.toml，余额为 CNY）----
    ds_balance = None
    try:
        ds_key = get_api_key()
        if ds_key:
            ds_balance = fetch_balance(ds_key)
        else:
            errors.append("D 未配置 DeepSeek API Key")
    except Exception as e:
        errors.append(f"D {e}")

    # ---- OpenRouter（/credits 账户余额，单位 USD）----
    or_balance_usd = None
    mgmt_key = get_or_mgmt_key()
    if mgmt_key:
        try:
            total_credits, total_usage = fetch_or_balance(mgmt_key)
            or_balance_usd = total_credits - total_usage
        except Exception as e:
            cached = load_last_balance(OR_BALANCE_LOG_PATH)
            if cached is not None:
                or_balance_usd = cached
                errors.append(f"R 获取余额失败，已用缓存余额显示: {e}")
            else:
                errors.append(f"R 获取余额失败: {e}")

    if ds_balance is None and or_balance_usd is None:
        print("? | refresh=true")
        print("---")
        print("⚠️ DeepSeek / OpenRouter 均不可用 | color=red")
        for e in errors:
            print(e)
        return

    # ---- DeepSeek 花费（基于余额日志推算）----
    today_spent = month_spent = seven_days_spent = 0.0
    ds_daily = []
    if ds_balance is not None:
        append_balance_log(BALANCE_LOG_PATH, ds_balance)
        ds_records = load_balance_log(BALANCE_LOG_PATH)
        now = datetime.now(BJT)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        today_spent = calc_spending(ds_records, today_start)
        month_spent = calc_spending(ds_records, month_start)
        seven_days_spent = calc_spending(ds_records, now - timedelta(days=7))
        ds_daily = get_daily_spending(ds_records)

    # ---- OpenRouter 花费（与 DeepSeek 同思路: 记余额差分，USD→CNY）----
    r_ok = or_balance_usd is not None
    r_today = r_month = r_7d = None
    or_daily = []
    or_remaining_cny = None
    if r_ok:
        append_balance_log(OR_BALANCE_LOG_PATH, or_balance_usd)
        or_records = load_balance_log(OR_BALANCE_LOG_PATH)
        now = datetime.now(BJT)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        r_today = calc_spending(or_records, today_start) * USD_CNY_RATE
        r_month = calc_spending(or_records, month_start) * USD_CNY_RATE
        r_7d = calc_spending(or_records, now - timedelta(days=7)) * USD_CNY_RATE
        or_daily = get_daily_spending(or_records)
        or_remaining_cny = or_balance_usd * USD_CNY_RATE

    # ---- 菜单栏标题：两家今日花费合计 ----
    total_today = (today_spent if ds_balance is not None else 0.0) + (
        r_today if r_today is not None else 0.0
    )
    print(f"{fmt2(total_today)} | font='Sarasa Mono SC' refresh=true size=13")
    print("---")
    print("9-12 14-18 | font='Sarasa Mono SC' size=13 refresh=true")
    # ---- 月度 / 7日 汇总（指标提到前面，D / R 同行）----
    m_parts = []
    if ds_balance is not None:
        m_parts.append(f"D {fmt2(month_spent)}")
    if r_ok:
        m_parts.append(f"R {fmt2(r_month)}")
    print(f"M  {'  '.join(m_parts)} | font='Sarasa Mono SC' size=13 refresh=true")
    d7_parts = []
    if ds_balance is not None:
        d7_parts.append(f"D {fmt2(seven_days_spent)}")
    if r_ok:
        d7_parts.append(f"R {fmt2(r_7d)}")
    print(f"7D {'  '.join(d7_parts)} | font='Sarasa Mono SC' size=13 refresh=true")
    print("---")

    # ---- 每日花费明细（日期提到前面，D / R 同行）----
    for i in range(5):
        label = None
        parts = []
        total = 0.0
        if ds_daily:
            label, d_val = ds_daily[i]
            parts.append(f"D {fmt2(d_val)}")
            total += d_val
        if or_daily:
            label, r_val = or_daily[i]
            parts.append(f"R {fmt2(r_val * USD_CNY_RATE)}")
            total += r_val
        if label is None or not parts:
            continue
        color = " color=#888888" if total == 0 else ""
        print(f"{label} {'  '.join(parts)} | font='Sarasa Mono SC' size=13{color} refresh=true")
    print("---")

    # ---- 余额（标题提到前面，D / R 同行）----
    bal_parts = []
    if ds_balance is not None:
        bal_parts.append(f"D{fmt2(ds_balance)}")
    if r_ok:
        bal_parts.append(f"R{fmt2(or_remaining_cny)}")
    print(f"余额  {'  '.join(bal_parts)} | font='Sarasa Mono SC' size=13 refresh=true")

    # ---- 提示与错误 ----
    if not mgmt_key:
        print("R 未配置环境变量 OPENROUTER_MANAGEMENT_KEY | font='Sarasa Mono SC' size=13 color=#888888 refresh=true")
    for e in errors:
        print(f"⚠️ {e} | color=red refresh=true")

    print("---")
    print("DeepSeek | href=https://platform.deepseek.com/usage")
    print("OpenRouter | href=https://openrouter.ai/credits")
    # print(f"刷新 | refresh=true terminal=false bash={__file__}")


if __name__ == "__main__":
    main()
