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

import calendar
import json
import os
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

CREDENTIALS_PATH = os.path.expanduser("~/.kimi-code/credentials/kimi-code.json")
USAGE_URL = "https://api.kimi.com/coding/v1/usages"

WEB_TOKEN_PATH = os.path.expanduser("~/.kimi-code/credentials/kimi-web-token.json")
WEBBRIDGE_URL = "http://127.0.0.1:10086/command"
WEBBRIDGE_BIN = os.path.expanduser("~/.kimi-webbridge/bin/kimi-webbridge")
WEBBRIDGE_SESSION = "kimi-usage-token-refresh"

# 归档目录：脚本所在目录下的 .archive/
ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".archive")
USAGE_RECORDS_PATH = os.path.join(ARCHIVE_DIR, "kimi_usage_records.jsonl")
MONTHLY_SUMMARY_PATH = os.path.join(ARCHIVE_DIR, "kimi_monthly_summary.jsonl")


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


# ---------- 月度用量 (www.kimi.com membership/quota) ----------

def get_web_token() -> str:
    with open(WEB_TOKEN_PATH, "r") as f:
        data = json.load(f)
    return data["access_token"]


def save_web_token(token: str) -> None:
    os.makedirs(os.path.dirname(WEB_TOKEN_PATH), exist_ok=True)
    with open(WEB_TOKEN_PATH, "w") as f:
        json.dump({"access_token": token}, f)


def webbridge_call(action: str, args: dict, timeout: float = 10):
    body = json.dumps({"action": action, "args": args, "session": WEBBRIDGE_SESSION}).encode("utf-8")
    req = urllib.request.Request(
        WEBBRIDGE_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def ensure_webbridge() -> bool:
    """尝试连接 WebBridge；未运行则自动启动。"""
    try:
        webbridge_call("list_tabs", {}, timeout=3)
        return True
    except Exception:
        pass

    if not os.path.exists(WEBBRIDGE_BIN):
        return False

    try:
        subprocess.run(
            [WEBBRIDGE_BIN, "start"],
            check=True,
            timeout=10,
            capture_output=True,
        )
        for _ in range(10):
            try:
                webbridge_call("list_tabs", {}, timeout=1)
                return True
            except Exception:
                time.sleep(0.3)
    except Exception:
        return False
    return False


def refresh_token_via_webbridge() -> str:
    """通过 WebBridge 从浏览器 localStorage 重新获取 access_token。"""
    if not ensure_webbridge():
        raise RuntimeError("Kimi WebBridge 未运行或无法启动")

    opened = False
    try:
        tabs_resp = webbridge_call("list_tabs", {}, timeout=3)
        tabs = tabs_resp.get("data", {}).get("tabs", [])
        kimi_tab = next(
            (t for t in tabs if "kimi.com" in t.get("url", "")),
            None,
        )
        if kimi_tab:
            webbridge_call("find_tab", {"url": kimi_tab["url"]}, timeout=3)
        else:
            webbridge_call(
                "navigate",
                {
                    "url": "https://www.kimi.com/membership/subscription?tab=quota",
                    "newTab": True,
                    "group_title": "Kimi 用量 Token 刷新",
                },
                timeout=5,
            )
            opened = True
            time.sleep(2)
    except Exception as e:
        raise RuntimeError(f"无法操作浏览器标签页: {e}")

    code = '(()=>{try{return localStorage.getItem("access_token")||""}catch(e){return ""}})()'
    try:
        result = webbridge_call("evaluate", {"code": code}, timeout=5)
        token = result.get("data", {}).get("value", "")
    except Exception as e:
        raise RuntimeError(f"无法读取浏览器 Token: {e}")

    if not token:
        raise RuntimeError("浏览器中未找到 access_token，请确认已登录 kimi.com")

    save_web_token(token)

    if opened:
        try:
            webbridge_call("close_tab", {}, timeout=3)
        except Exception:
            pass

    return token


def get_valid_web_token(allow_refresh: bool = True) -> str:
    """获取有效的 www.kimi.com access_token；过期时尝试通过 WebBridge 刷新。"""
    try:
        token = get_web_token()
        # 用轻量接口验证 token
        req = urllib.request.Request(
            "https://www.kimi.com/apiv2/kimi.gateway.membership.v2.MembershipService/GetSubscription",
            data=b"{}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=5):
            return token
    except urllib.error.HTTPError as e:
        if e.code == 401 and allow_refresh:
            refresh_token_via_webbridge()
            return get_web_token()
        raise


def fetch_subscription(token: str) -> dict:
    """获取会员订阅/额度总览，并转换为旧的 subscriptionBalance 兼容格式。"""
    url = "https://www.kimi.com/apiv2/kimi.gateway.membership.v2.MembershipService/GetSubscription"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.load(resp)

    balances = data.get("balances", [])
    # 优先取全站通用额度（FEATURE_OMNI），否则取第一个订阅类额度
    balance = next(
        (b for b in balances if b.get("feature") == "FEATURE_OMNI"),
        next((b for b in balances if b.get("type") == "SUBSCRIPTION"), {}),
    )
    return {
        "subscriptionBalance": {
            "amountUsedRatio": balance.get("amountUsedRatio", 0),
            "expireTime": balance.get("expireTime", ""),
        },
        "ratelimitCode5h": {},
        "ratelimitCode7d": {},
    }


def fetch_balance_actions(token: str, page_token: str = "", page_size: int = 100) -> dict:
    url = "https://www.kimi.com/apiv2/kimi.gateway.membership.v2.MembershipService/ListBalanceActions"
    payload = json.dumps({"pageSize": page_size, "pageToken": page_token}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def archive_monthly_usage(stat: dict, actions: list) -> None:
    """把月度用量总览和明细记录追加/合并到 .archive/ 目录。"""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    # 1) 总览：每个运行周期记录一条（按天去重，同一天保留最新）
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    summary_entry = {
        "date": today,
        "recorded_at": now.isoformat(),
        "subscription_balance": stat.get("subscriptionBalance", {}),
        "ratelimit_5h": stat.get("ratelimitCode5h", {}),
        "ratelimit_7d": stat.get("ratelimitCode7d", {}),
    }

    summaries = []
    if os.path.exists(MONTHLY_SUMMARY_PATH):
        with open(MONTHLY_SUMMARY_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        summaries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    # 按日期去重，保留最新
    summaries = [s for s in summaries if s.get("date") != today]
    summaries.append(summary_entry)
    summaries.sort(key=lambda x: x.get("date", ""))

    with open(MONTHLY_SUMMARY_PATH, "w", encoding="utf-8") as f:
        for s in summaries:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    # 2) 明细记录：按 action id 去重合并
    existing_ids = set()
    existing_records = []
    if os.path.exists(USAGE_RECORDS_PATH):
        with open(USAGE_RECORDS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        if rec.get("id"):
                            existing_ids.add(rec["id"])
                        existing_records.append(rec)
                    except json.JSONDecodeError:
                        pass

    new_count = 0
    with open(USAGE_RECORDS_PATH, "a", encoding="utf-8") as f:
        for action in actions:
            action_id = action.get("id")
            if not action_id or action_id in existing_ids:
                continue
            existing_ids.add(action_id)
            # 展开 items，取第一条的 amountRatio
            items = action.get("items", [])
            amount_ratio = items[0].get("amountRatio") if items else None
            record = {
                "id": action_id,
                "timestamp": action.get("timestamp"),
                "feature": action.get("feature"),
                "title": action.get("title"),
                "status": action.get("status"),
                "amount_ratio": amount_ratio,
                "recorded_at": now.isoformat(),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            new_count += 1

    return new_count


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
    # ---------- 月度用量 (www.kimi.com) ----------
    monthly_error = ""
    monthly_stat = None
    monthly_actions = []
    try:
        web_token = get_valid_web_token(allow_refresh=True)
        monthly_stat = fetch_subscription(web_token)
        # 获取最近若干条明细（按时间倒序），用于归档；限制页数避免刷新超时
        actions_resp = fetch_balance_actions(web_token, page_size=50)
        monthly_actions = actions_resp.get("actions", [])
        next_token = actions_resp.get("nextPageToken", "")
        for _ in range(2):  # 最多再取 2 页
            if not next_token:
                break
            page = fetch_balance_actions(web_token, page_token=next_token, page_size=50)
            monthly_actions.extend(page.get("actions", []))
            next_token = page.get("nextPageToken", "")
        archive_monthly_usage(monthly_stat, monthly_actions)
    except Exception as e:
        monthly_error = str(e)

    # ---------- Kimi Code 用量 (api.kimi.com) ----------
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

    # 月度用量摘要
    monthly_display = ""
    monthly_expire = ""
    monthly_diff_display = ""
    if monthly_stat:
        sb = monthly_stat.get("subscriptionBalance", {})
        amount_ratio = sb.get("amountUsedRatio", 0) or 0
        expire_time = sb.get("expireTime", "")
        monthly_display = f"{amount_ratio:.1%}"
        if expire_time:
            try:
                expire_dt = datetime.fromisoformat(expire_time.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                days_left = (expire_dt - now).days
                monthly_expire = f"{days_left}D"
                # 按月度周期线性估算预期用量差值（expire_time 同月同日作为周期起点）
                try:
                    year, month = expire_dt.year, expire_dt.month
                    if month == 1:
                        prev_year, prev_month = year - 1, 12
                    else:
                        prev_year, prev_month = year, month - 1
                    last_day = calendar.monthrange(prev_year, prev_month)[1]
                    start_day = min(expire_dt.day, last_day)
                    start_dt = expire_dt.replace(year=prev_year, month=prev_month, day=start_day)
                except Exception:
                    start_dt = expire_dt - timedelta(days=30)
                elapsed = (now - start_dt).total_seconds()
                total = (expire_dt - start_dt).total_seconds()
                if total > 0 and elapsed > 0:
                    elapsed = min(elapsed, total)
                    expected_ratio = elapsed / total
                    diff = amount_ratio - expected_ratio
                    monthly_diff_display = f"{diff:+.0%}"
            except Exception:
                monthly_expire = expire_time

    # 周配额已用完 → 只显示 W 重置时间，隐藏 H 及差值（反正超配额用不了）
    if w_ratio >= 1:
        title = f"W {w_display}"
    else:
        title = f"W {w_display} H {h_display}"
        if diff_display:
            title += f" {diff_display}%"
    print(f"{title} | font='Sarasa Mono SC' refresh=true size=13")
    print("---")

    # 下拉菜单详情
    if reset_time:
        print(f"{format_reset_time(reset_time)} | refresh=true font='Sarasa Mono SC' size=13")
    if min300_reset and w_ratio < 1:
        h_disp = format_reset_time(min300_reset)
        if min300_diff_display:
            h_disp += f" {min300_diff_display}"
        print(f"{h_disp} | refresh=true font='Sarasa Mono SC' size=13")
    if monthly_display:
        m_line = monthly_expire
        if monthly_expire:
            m_line += f" {monthly_display}"
        else:
            m_line = monthly_display
        if monthly_diff_display:
            m_line += f" {monthly_diff_display}"
        print(f"{m_line} | refresh=true font='Sarasa Mono SC' size=13")
    print("---")

    if monthly_error:
        print(f"月度用量获取失败: {monthly_error} | color=red refresh=true")
        print("---")

    print("Kimi Console | href=https://www.kimi.com/code/console")
    print("Beta | href=https://www.kimi.com/code/beta")


if __name__ == "__main__":
    main()
