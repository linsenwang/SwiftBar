#!/usr/bin/env python3
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>

"""
SwiftBar 插件: NetNewsWire 未读数

- 菜单栏显示未读总数，非 0 时蓝色
- 左键点击：标题先显示「抓取中」，触发 NetNewsWire 抓取，完成后显示
  「抓取完成」听一会，再还原成纯数字
- 右键：查看各账号未读数、上次抓取成功时间
- 定时刷新另外由 local_rss 的 run.sh 负责
"""

import datetime as dt
import json
import plistlib
import sqlite3
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

ACCOUNTS_DIR = (
    Path.home()
    / "Library"
    / "Containers"
    / "com.ranchero.NetNewsWire-Evergreen"
    / "Data"
    / "Library"
    / "Application Support"
    / "NetNewsWire"
    / "Accounts"
)
CACHE_PATH = Path.home() / "Library" / "Caches" / "swiftbar-netnewswire.json"
REQUEST_PATH = Path.home() / "Library" / "Caches" / "swiftbar-netnewswire.request"

FETCH_SETTLE_SECONDS = 2.5
DONE_SHOW_SECONDS = 0.1
UI_STATE_TTL = 30

REFRESH_SCRIPT = """
tell application "System Events"
    if not (exists process "NetNewsWire") then return "not-running"
    tell process "NetNewsWire"
        try
            perform action "AXPress" of menu item "Refresh" of menu 1 of menu bar item "File" of menu bar 1
            return "ok"
        end try
        repeat with mbi in menu bar items of menu bar 1
            try
                perform action "AXPress" of menu item "Refresh" of menu 1 of mbi
                return "ok"
            end try
        end repeat
    end tell
end tell
return "no-menu"
"""


def plugin_path() -> str:
    return str(Path(sys.argv[0]).resolve())


def load_cache() -> dict:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(cache: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        tmp.replace(CACHE_PATH)
    except OSError:
        pass


def read_settings(account_dir: Path) -> dict:
    try:
        with open(account_dir / "Settings.plist", "rb") as f:
            data = plistlib.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, plistlib.InvalidFileException, ValueError):
        return {}


def active_accounts() -> list:
    """返回 [(账号名, DB 路径), ...]，只包含 NetNewsWire 中启用的账号。"""
    accounts = []
    if not ACCOUNTS_DIR.is_dir():
        return accounts
    for account_dir in sorted(ACCOUNTS_DIR.iterdir()):
        db_path = account_dir / "DB.sqlite3"
        if not db_path.is_file():
            continue
        settings = read_settings(account_dir)
        if not settings.get("isActive"):
            continue
        name = (
            settings.get("name")
            or settings.get("username")
            or ("On My Mac" if account_dir.name == "OnMyMac" else "账号")
        )
        accounts.append((name, db_path))
    return accounts


def unread_count(db_path: Path) -> int:
    quoted = urllib.parse.quote(str(db_path))
    con = sqlite3.connect(f"file:{quoted}?mode=ro", uri=True, timeout=2.0)
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM statuses s "
            "JOIN articles a ON a.articleID = s.articleID "
            "WHERE s.read = 0"
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        con.close()


def app_running() -> bool:
    return subprocess.run(
        ["/usr/bin/pgrep", "-x", "NetNewsWire"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def trigger_refresh() -> tuple:
    """后台按下 NetNewsWire 的 Refresh 菜单项。返回 (成功与否, 错误信息)。"""
    if not app_running():
        subprocess.run(
            ["/usr/bin/open", "-a", "NetNewsWire"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(20):
            if app_running():
                break
            time.sleep(0.25)
        time.sleep(1.5)

    last_error = ""
    for _ in range(3):
        try:
            proc = subprocess.run(
                ["/usr/bin/osascript", "-e", REFRESH_SCRIPT],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except subprocess.TimeoutExpired:
            return False, "调用刷新超时"

        output = (proc.stdout or "").strip()
        last_error = (proc.stderr or "").strip().splitlines()[0] if proc.stderr else ""

        if proc.returncode == 0 and output == "ok":
            return True, ""
        if output == "not-running":
            return False, "NetNewsWire 未运行"
        if output == "no-menu":
            time.sleep(0.5)
            continue
        if last_error:
            return False, last_error[:120]
        return False, "未找到 Refresh 菜单项"

    return False, "未找到 Refresh 菜单项（可能缺少辅助功能权限）"


def fmt_time(ts: float) -> str:
    value = dt.datetime.fromtimestamp(ts)
    if value.date() == dt.datetime.now().date():
        return value.strftime("%H:%M:%S")
    return value.strftime("%m-%d %H:%M:%S")


def take_request() -> bool:
    """run.sh 抓取完成后会写一个请求文件，由插件（SwiftBar 的权限）去刷新 NNW。"""
    try:
        raw = REQUEST_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    try:
        REQUEST_PATH.unlink()
    except OSError:
        pass
    try:
        requested_at = float(raw)
    except ValueError:
        return False
    return time.time() - requested_at <= 300


def refresh_plugin() -> None:
    # SwiftBar 2.1.x 里插件 ID 是绝对路径，refreshplugin 只认短名；传完整文件名匹配不到（2.1.2 才修复）
    name = urllib.parse.quote(Path(sys.argv[0]).name.split(".")[0])
    subprocess.run(
        ["/usr/bin/open", "-g", f"swiftbar://refreshplugin?name={name}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def handle_click(cache: dict) -> None:
    seq = int(cache.get("ui_seq", 0) or 0) + 1
    cache["ui_seq"] = seq
    cache["ui_state"] = "fetching"
    cache["ui_state_time"] = time.time()
    save_cache(cache)
    refresh_plugin()

    ok, message = trigger_refresh()
    if not ok:
        latest = load_cache()
        if int(latest.get("ui_seq", 0) or 0) == seq:
            latest["ui_state"] = ""
            latest["ui_state_time"] = time.time()
            latest["last_error"] = message
            save_cache(latest)
        refresh_plugin()
        return

    time.sleep(FETCH_SETTLE_SECONDS)
    latest = load_cache()
    if int(latest.get("ui_seq", 0) or 0) != seq:
        return
    latest["last_success"] = time.time()
    latest["last_error"] = ""
    latest["ui_state"] = "done"
    latest["ui_state_time"] = time.time()
    save_cache(latest)
    refresh_plugin()

    time.sleep(DONE_SHOW_SECONDS)
    latest = load_cache()
    if int(latest.get("ui_seq", 0) or 0) == seq and latest.get("ui_state") == "done":
        latest["ui_state"] = ""
        latest["ui_state_time"] = time.time()
        save_cache(latest)
    refresh_plugin()


def main() -> None:
    cache = load_cache()

    if sys.argv[1:2] == ["--click"]:
        handle_click(cache)
        return

    if take_request():
        ok, message = trigger_refresh()
        if ok:
            time.sleep(FETCH_SETTLE_SECONDS)
            cache["last_success"] = time.time()
            cache["last_error"] = ""
        else:
            cache["last_error"] = message
        save_cache(cache)

    per_account = []
    total = 0
    error = ""
    for name, db_path in active_accounts():
        try:
            count = unread_count(db_path)
        except (sqlite3.Error, OSError) as exc:
            error = str(exc)
            count = 0
        per_account.append((name, count))
        total += count

    action = (
        f"bash={sys.executable or '/usr/bin/python3'} param1={plugin_path()} "
        "param2=--click terminal=false"
    )
    ui_state = str(cache.get("ui_state", ""))
    ui_state_time = float(cache.get("ui_state_time", 0) or 0)
    if ui_state and time.time() - ui_state_time > UI_STATE_TTL:
        ui_state = ""

    if error:
        title, suffix = "?", " color=red"
    elif ui_state == "fetching":
        title, suffix = "抓取中", ""
    elif ui_state == "done":
        title, suffix = "抓取完成", ""
    elif total > 0:
        title, suffix = str(total), " color=#007AFF"
    else:
        title, suffix = "0", ""
    print(f"{title} | {action}{suffix}")

    print("---")
    for name, count in per_account:
        color = "#FF6600" if count else "#888888"
        print(f"{name}: {count} | size=12 color={color}")
    if not per_account:
        print("未读取到 NetNewsWire 账号 | size=12 color=#888888")

    print("---")
    last_success = float(cache.get("last_success", 0) or 0)
    if last_success:
        print(f"上次抓取成功: {fmt_time(last_success)} | size=12 color=#888888")
    else:
        print("上次抓取成功: 无 | size=12 color=#888888")

    if cache.get("last_error"):
        message = str(cache["last_error"])
        print(f"抓取失败: {message} | size=12 color=red")
        lowered = message.lower()
        if any(k in lowered for k in ("assistive", "-1719", "25211", "listen event")):
            print("需要给 SwiftBar 开启「辅助功能」权限 | size=12 color=red")
            print(
                "打开辅助功能设置 | bash=/usr/bin/open "
                "param1=x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility "
                "terminal=false"
            )
            print(
                "打开自动化设置 | bash=/usr/bin/open "
                "param1=x-apple.systempreferences:com.apple.preference.security?Privacy_Automation "
                "terminal=false"
            )


if __name__ == "__main__":
    main()
