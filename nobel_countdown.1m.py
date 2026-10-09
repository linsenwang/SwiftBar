#!/usr/bin/env python3
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>
# <swiftbar.refreshOnOpen>true</swiftbar.refreshOnOpen>

"""
SwiftBar 插件: 诺贝尔奖下一场公布
刷新频率: 1 分钟（文件名里的 .1m. 控制）

菜单栏显示离下一场公布还有多久，例如「物理 剩17小时33分」——
1 分钟才刷新一次，所以只显示到分钟，不跳秒。
下拉里给出这次公布的北京时间（站点只给 UTC，这里换算成 Asia/Shanghai）。
标题不写 color=，跟随系统菜单栏配色；全文不用 emoji。

数据来源（没有 API，时间是写在 HTML 属性里的）
------------------------------------------------
https://www.nobelprize.org/ 首页里有这么一段：

    <section class="countdown"
             data-due="Oct 6 2026, 09:45:00 UTC"
             data-template="message-3f69142f-cea4-4200-b8e4-b4167e62fab0">
      <header class="section-header"><h3>Next announcement</h3></header>
      <div class="countdown-container secondary">
        <h4 class="countdown-title">Nobel Prize in Physics 2026</h4>
        <div class="countdown-content js-countdown-content"></div>
        <script type="text/html" id="message-3f69142f-...">Live</script>
      </div>
    </section>

主题的 frontend.js 就是照着这些属性在前端逐秒渲染的（逻辑等价于）：

    const due  = new Date(section.dataset.due);   // data-due 是 UTC 时间
    const left = due - Date.now();
    if (left > 0) { 渲染 天/时/分/秒 }
    else          { 渲染 data-template 指向的 <script> 文案 }   // 也就是 "Live"

用浏览器抓包确认过：整页 HTML 之外没有任何 xhr / fetch / json 请求，
所以本插件做的是同一件事 —— 抓首页、把 data-due 和标题抠出来。
（.countdown-container 带 secondary 表示「下一场」，本插件优先取它，
  万一只剩 primary 就退回取 primary。）

取数据与刷新策略
----------------
每分钟的刷新基本只读本地缓存，不碰网络。缓存放在
~/.cache/swiftbar/nobel_prize_countdown.json，重新抓取的时机：

- 公布时间还没到：6 小时内不再抓（页面上的时间不会自己变）
- 已经过点：每分钟抓一次，等页面换成下一场（届时 data-due 会变成新时间）
- 页面上没有倒计时段（本年度都公布完了）：每 30 分钟抓一次

用法
----
    python3 nobel_countdown.1m.py            输出 SwiftBar 菜单
    python3 nobel_countdown.1m.py --refresh  强制重新抓取（菜单里的「立即刷新」）
    python3 nobel_countdown.1m.py --raw      打印抓到的原始字段，排查用
"""

import argparse
import html
import json
import re
import shlex
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# -----------------------------------------------------------------------------
# 配置
# -----------------------------------------------------------------------------
URL = "https://www.nobelprize.org/"
SCRIPT_PATH = Path(__file__).resolve()
CACHE_PATH = Path.home() / ".cache" / "swiftbar" / "nobel_prize_countdown.json"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

TTL_BEFORE = 6 * 3600   # 还没到点：6 小时内不重复抓
TTL_AFTER = 60          # 已过点：每分钟抓一次，等下一场
TTL_EMPTY = 30 * 60     # 页面上没有倒计时：30 分钟抓一次
TTL_ERROR = 60          # 抓失败时，最短重试间隔

FONT = "font='Sarasa Mono SC'"
COLOR_DIM = "#888888"
COLOR_ERR = "#FF3B30"

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 站点给的是 UTC，菜单里一律按北京时间展示
try:
    from zoneinfo import ZoneInfo

    CN_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # 系统没有 tzdata 时退回固定 +8
    CN_TZ = timezone(timedelta(hours=8))

# data-due 的样子：Oct 6 2026, 09:45:00 UTC
DUE_RE = re.compile(
    r"^([A-Za-z]{3,9})\.?\s+(\d{1,2})\s*,?\s+(\d{4}),?\s+"
    r"(\d{1,2}):(\d{2}):(\d{2})\s*([A-Za-z]{0,5}[+-]?\d{0,4})?$"
)

SECTION_RE = re.compile(r"<section[^>]*>")
CONTAINER_RE = re.compile(r'class="([^"]*countdown-container[^"]*)"')
CLASS_RE = re.compile(r'class="([^"]*)"')
TITLE_RE = re.compile(r'<h4 class="countdown-title">(.*?)</h4>', re.S)

# 标题 → 菜单栏用的短标签，顺序有意义（先匹配长的）
PRIZE_LABELS = (
    ("Physiology or Medicine", "医学"),
    ("Medicine", "医学"),
    ("Physics", "物理"),
    ("Chemistry", "化学"),
    ("Literature", "文学"),
    ("Peace", "和平"),
    ("Economic Sciences", "经济学"),
    ("Economics", "经济学"),
)


# -----------------------------------------------------------------------------
# 工具
# -----------------------------------------------------------------------------
def esc(text: str) -> str:
    """SwiftBar 只用第一个 "|" 切分标题和参数，标题里的竖线得转义。"""
    return str(text).replace("|", "\\|").replace("\n", " ")


def attr(tag: str, name: str) -> str:
    m = re.search(r'%s="([^"]*)"' % re.escape(name), tag)
    return html.unescape(m.group(1)) if m else ""


def class_tokens(tag: str) -> list:
    m = CLASS_RE.search(tag)
    return m.group(1).split() if m else []


def tzinfo_of(name: str):
    """data-due 的时区后缀，这个站永远是 UTC；顺手认几个常见的。"""
    key = (name or "").strip().upper()
    if key in ("UTC", "GMT", "Z", "UT", ""):
        return timezone.utc
    fixed = {"CET": 1, "CEST": 2, "BST": 1, "EST": -5, "EDT": -4}
    if key in fixed:
        return timezone(timedelta(hours=fixed[key]))
    m = re.match(r"^(?:GMT|UTC)?([+-])(\d{1,2})(?::?(\d{2}))?$", key)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        minutes = int(m.group(2)) * 60 + int(m.group(3) or 0)
        return timezone(sign * timedelta(minutes=minutes))
    return timezone.utc


def parse_due(text: str) -> datetime:
    """把 data-due / 缓存里的 ISO 字符串解析成 aware datetime。"""
    text = (text or "").strip()
    m = DUE_RE.match(text)
    if not m:
        return datetime.fromisoformat(text)  # 缓存里写的是 ISO 格式
    mon, day, year, hh, mm, ss, tz = m.groups()
    month = MONTHS.get(mon[:3].lower())
    if not month:
        raise ValueError(f"看不懂 data-due 里的月份: {text!r}")
    return datetime(
        int(year), month, int(day), int(hh), int(mm), int(ss),
        tzinfo=tzinfo_of(tz),
    )


def find_container(page: str):
    """定位 .countdown-container，优先带 secondary 的那个（= 下一场公布）。"""
    fallback = None
    for m in CONTAINER_RE.finditer(page):
        classes = m.group(1).split()
        if "countdown-container" not in classes:
            continue
        if "secondary" in classes:
            return m.start()
        if fallback is None:
            fallback = m.start()
    return fallback


# -----------------------------------------------------------------------------
# 抓取与缓存
# -----------------------------------------------------------------------------
def extract(page: str) -> dict:
    """从首页 HTML 里抠出「下一场公布」的时间与标题。"""
    start = find_container(page)
    if start is None:
        return {"status": "empty", "title": "", "due": "", "due_raw": "", "live": ""}

    sections = [
        m for m in SECTION_RE.finditer(page)
        if m.start() < start and "countdown" in class_tokens(m.group(0))
    ]
    if not sections:
        raise ValueError('找到了 countdown-container，但前面没有 <section class="countdown">')
    tag = sections[-1].group(0)

    due_raw = attr(tag, "data-due")
    if not due_raw:
        raise ValueError("section.countdown 上没有 data-due")
    due = parse_due(due_raw)

    m = TITLE_RE.search(page[start:])
    title = html.unescape(m.group(1)).strip() if m else ""

    live = ""
    tmpl = attr(tag, "data-template")
    if tmpl:
        lm = re.search(
            r'<script type="text/html" id="%s">(.*?)</script>' % re.escape(tmpl),
            page, re.S,
        )
        if lm:
            live = html.unescape(lm.group(1)).strip()

    return {
        "status": "ok",
        "title": title,
        "due_raw": due_raw,
        "due": due.isoformat(),
        "live": live or "Live",
    }


def fetch_remote() -> dict:
    req = urllib.request.Request(
        f"{URL}?_={int(time.time())}",
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        page = resp.read().decode("utf-8", "replace")
    data = extract(page)
    data["fetched_at"] = time.time()
    return data


def load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(data: dict) -> dict:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass
    return data


def cache_age(cache: dict) -> float:
    try:
        return time.time() - float(cache.get("fetched_at") or 0)
    except Exception:
        return 1e9


def needs_fetch(cache: dict) -> bool:
    if not cache:
        return True
    age = cache_age(cache)
    if cache.get("status") == "ok" and cache.get("due"):
        try:
            due = parse_due(cache["due"])
        except Exception:
            return age > TTL_EMPTY
        if datetime.now(timezone.utc) < due:
            return age > TTL_BEFORE
        return age > TTL_AFTER
    # 上次没抓到东西（页面上没倒计时，或者抓失败了）
    ttl = TTL_ERROR if cache.get("error") else TTL_EMPTY
    return age > ttl


# -----------------------------------------------------------------------------
# 展示
# -----------------------------------------------------------------------------
def short_label(title: str) -> str:
    low = (title or "").lower()
    for key, label in PRIZE_LABELS:
        if key.lower() in low:
            return label
    return "诺奖"


def left_text(seconds: int) -> str:
    """菜单栏上的剩余时间：1 分钟刷新一次，所以最大到分钟。"""
    days, rem = divmod(max(seconds, 0), 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f"{days}天{hours}小时"
    if hours:
        return f"{hours}小时{mins}分"
    if mins:
        return f"{mins}分"
    return "不到1分"


def cn_time(moment: datetime) -> str:
    """北京时间全称，带上星期几。"""
    cn = moment.astimezone(CN_TZ)
    return f"{cn.strftime('%Y-%m-%d %H:%M')}（{WEEKDAYS[cn.weekday()]}）"


def age_text(cache: dict) -> str:
    if not cache.get("fetched_at"):
        return "尚无缓存（还没成功抓过）"
    age = int(cache_age(cache))
    if age < 60:
        return f"{age} 秒前"
    if age < 3600:
        return f"{age // 60} 分钟前"
    if age < 86400:
        return f"{age // 3600} 小时前"
    return f"{age // 86400} 天前"


def line(text: str, *params: str) -> str:
    return f"{esc(text)} | " + " ".join([FONT, *params])


def refresh_action() -> str:
    return (
        f"bash={sys.executable} param1={shlex.quote(str(SCRIPT_PATH))} "
        f"param2=--refresh terminal=false refresh=true"
    )


def print_menu(cache: dict, error: str) -> None:
    now = datetime.now(timezone.utc)

    due: Optional[datetime] = None
    if cache.get("status") == "ok" and cache.get("due"):
        try:
            due = parse_due(cache["due"])
        except Exception:
            due = None

    title = cache.get("title") or ""
    label = short_label(title)
    passed = due is not None and now >= due

    # --- 菜单栏标题：剩余时间 ---
    if cache.get("status") == "empty":
        print(line(f"{label} 待公布", "size=13", "refresh=true"))
    elif due is None:
        print(line(f"{label} --", "size=13", "refresh=true"))
    elif passed:
        print(line(f"{label} 已公布", "size=13", "refresh=true"))
    else:
        left = int((due - now).total_seconds())
        print(line(f"{label} 剩{left_text(left)}", "size=13", "refresh=true"))

    print("---")

    # --- 详情 ---
    if cache.get("status") == "empty":
        print(line("首页上暂时没有倒计时段", f"size=12 color={COLOR_DIM}"))
        print(line("多半是本年度奖项已全部公布完", f"size=12 color={COLOR_DIM}"))
    elif due is None:
        print(line("还没取到数据", f"size=12 color={COLOR_ERR}"))
    else:
        print(line(title or "（没读到标题）", "size=13"))
        print(line(f"北京时间 {cn_time(due)}", "size=13"))
        if passed:
            print(line(
                f"公布时间已过，页面此刻显示「{cache.get('live') or 'Live'}」",
                f"size=12 color={COLOR_ERR}",
            ))
        print(line(f"站点原文 {cache.get('due_raw') or ''}", f"size=12 color={COLOR_DIM}"))

    print("---")
    print(f"在 nobelprize.org 打开首页 | {FONT} size=12 href={URL} refresh=true")
    print(line("立即重新抓取", "size=12", refresh_action()))
    print("---")

    if error:
        print(line(f"最近一次抓取失败: {error}", f"size=12 color={COLOR_ERR}"))
        if due is not None or cache.get("status") == "empty":
            print(line("下面显示的是缓存里的旧数据", f"size=12 color={COLOR_DIM}"))
    print(line(f"数据抓取于 {age_text(cache)}", f"size=12 color={COLOR_DIM}"))


# -----------------------------------------------------------------------------
# 入口
# -----------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="强制重新抓取")
    parser.add_argument("--raw", action="store_true", help="打印原始字段")
    args = parser.parse_args()

    cache = load_cache()
    error = ""

    if args.raw:
        print(json.dumps(cache, ensure_ascii=False, indent=2))
        return

    if args.refresh or needs_fetch(cache):
        try:
            cache = save_cache(fetch_remote())
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if cache:
                cache["error"] = error
                save_cache(cache)

    print_menu(cache, error)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # 插件里抛异常整个菜单就没了，兜一下
        print(f"诺奖 出错 | {FONT} size=13 color={COLOR_ERR} refresh=true")
        print("---")
        print(f"插件出错: {esc(f'{type(exc).__name__}: {exc}')} | {FONT} size=12 color={COLOR_ERR}")
