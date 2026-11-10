#!/usr/bin/env python3
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>

"""
SwiftBar 插件: BetterDisplay 重初始化显示器

左键点击菜单栏标题，执行:
    BetterDisplay cli perform -reinitialize -name="Mi Monitor"

执行结果（成功 ✓ / 失败 ✕）会在标题上停留一小会儿。
"""

import json
import subprocess
import sys
import time
from pathlib import Path

CLI = "/Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay"
TITLE = "Mi"
DISPLAY_NAME = "Mi Monitor"
STATE_PATH = Path.home() / "Library/Caches" / "swiftbar-betterdisplay-reinit.json"
CLI_TIMEOUT = 30
DONE_TTL = 40


def reinit() -> None:
    ok = False
    try:
        result = subprocess.run(
            [CLI, "cli", "perform", "-reinitialize", f"-name={DISPLAY_NAME}"],
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT,
        )
        ok = result.returncode == 0
        output = (result.stdout or "") + (result.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        output = str(exc)

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"ts": time.time(), "ok": ok, "output": output[-400:]}),
        encoding="utf-8",
    )


def render() -> None:
    title, color = TITLE, ""
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if time.time() - state.get("ts", 0) < DONE_TTL:
            if state.get("ok"):
                title, color = f"{TITLE} ✓", "green"
            else:
                title, color = f"{TITLE} ✕", "red"
    except (OSError, ValueError):
        pass

    attrs = [
        f"bash={sys.executable}",
        f"param1={Path(__file__).resolve()}",
        "param2=--reinit",
        "terminal=false",
        "refresh=true",
        "size=10",
        "tooltip=重新初始化 Mi Monitor（BetterDisplay）",
    ]
    if color:
        attrs.append(f"color={color}")
    print(f"{title} | {' '.join(attrs)}")


if __name__ == "__main__":
    if "--reinit" in sys.argv:
        reinit()
    else:
        render()
