#!/usr/bin/env python3
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>

"""
SwiftBar / xbar 插件: Kimi Code Beta 模式切换
安装:
1. 复制到 SwiftBar 插件目录:
   cp kimi_beta_mode.2m.py "$HOME/Library/Application Support/SwiftBar/plugins/"
2. 确保可执行: chmod +x "$HOME/Library/Application Support/SwiftBar/plugins/kimi_beta_mode.2m.py"

刷新频率: 2分钟

说明:
- 菜单栏显示 L（K2.7 Code 正常版）或 H（K2.7 Code 高速版）
- 点击菜单栏即可切换模式
- 需要 web access_token，读取 ~/.kimi-code/credentials/kimi-web-token.json
- Token 过期时会尝试通过 Kimi WebBridge 从浏览器 localStorage 自动刷新
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

WEB_TOKEN_PATH = os.path.expanduser("~/.kimi-code/credentials/kimi-web-token.json")
BETA_API_BASE = "https://www.kimi.com/apiv2/kimi.gateway.code.v1.BetaService"
WEBBRIDGE_URL = "http://127.0.0.1:10086/command"
WEBBRIDGE_BIN = os.path.expanduser("~/.kimi-webbridge/bin/kimi-webbridge")
WEBBRIDGE_SESSION = "kimi-beta-token-refresh"


def plugin_path() -> str:
    return os.path.abspath(sys.argv[0])


def get_web_token() -> str:
    with open(WEB_TOKEN_PATH, "r") as f:
        data = json.load(f)
    return data["access_token"]


def save_web_token(token: str) -> None:
    os.makedirs(os.path.dirname(WEB_TOKEN_PATH), exist_ok=True)
    with open(WEB_TOKEN_PATH, "w") as f:
        json.dump({"access_token": token}, f)


def beta_api_request(endpoint: str, body: dict, token: str):
    url = f"{BETA_API_BASE}/{endpoint}"
    payload = json.dumps(body).encode("utf-8")
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


def fetch_beta_status(token: str) -> dict:
    return beta_api_request("GetBeta", {}, token)


def select_beta_model(model: str, token: str) -> dict:
    return beta_api_request("SelectBetaModel", {"model": model}, token)


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
        # 等待 daemon 就绪
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

    # 优先复用已打开的 kimi.com 标签页，避免打扰用户
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
                    "url": "https://www.kimi.com/code/beta",
                    "newTab": True,
                    "group_title": "Kimi Beta Token Refresh",
                },
                timeout=5,
            )
            opened = True
            time.sleep(2)  # 等待页面加载完成
    except Exception as e:
        raise RuntimeError(f"无法操作浏览器标签页: {e}")

    # 从 localStorage 读取 access_token
    code = '(()=>{try{return localStorage.getItem("access_token")||""}catch(e){return ""}})()'
    try:
        result = webbridge_call("evaluate", {"code": code}, timeout=5)
        token = result.get("data", {}).get("value", "")
    except Exception as e:
        raise RuntimeError(f"无法读取浏览器 Token: {e}")

    if not token:
        raise RuntimeError("浏览器中未找到 access_token，请确认已登录 kimi.com")

    save_web_token(token)

    # 如果是插件自己打开的标签页，用完关闭
    if opened:
        try:
            webbridge_call("close_tab", {}, timeout=3)
        except Exception:
            pass

    return token


def get_valid_token(allow_refresh: bool = True) -> str:
    """获取有效 token；过期且允许刷新时自动通过 WebBridge 更新。"""
    try:
        token = get_web_token()
        fetch_beta_status(token)
        return token
    except urllib.error.HTTPError as e:
        if e.code == 401 and allow_refresh:
            refresh_token_via_webbridge()
            token = get_web_token()
            fetch_beta_status(token)
            return token
        raise


def toggle_beta_mode():
    token = get_valid_token()
    beta = fetch_beta_status(token)
    current = beta.get("beta", {}).get("selectedModel", "")
    target = "k2.7-code" if current == "k2.7-code-highspeed" else "k2.7-code-highspeed"
    select_beta_model(target, token)


def print_menu(current: str, label: str, target: str, error_msg: str = ""):
    script = plugin_path()
    print(
        f"{label} | bash={sys.executable} param1={script} param2=--toggle "
        f"terminal=false refresh=true"
    )
    print("---")
    if current == "k2.7-code-highspeed":
        print("当前: K2.7 Code 高速版 (HS)")
    elif current:
        print("当前: K2.7 Code 正常版 (L)")
    print("切换模式 | bash={} param1={} param2=--toggle terminal=false refresh=true".format(
        sys.executable, script
    ))
    print("刷新 Token | bash={} param1={} param2=--refresh-token terminal=false refresh=true".format(
        sys.executable, script
    ))
    if error_msg:
        print("---")
        print(f"⚠️ {error_msg} | color=red")


def main():
    try:
        token = get_valid_token(allow_refresh=True)
        beta = fetch_beta_status(token)
        current = beta.get("beta", {}).get("selectedModel", "")
    except urllib.error.HTTPError as e:
        print("Kβ? | href=https://www.kimi.com/code/beta")
        print("---")
        print(f"API 错误: {e.code} {e.reason} | color=red")
        return
    except Exception as e:
        print("Kβ? | href=https://www.kimi.com/code/beta")
        print("---")
        print(f"Token 失效，自动刷新失败: {e} | color=red")
        script = plugin_path()
        print("刷新 Token | bash={} param1={} param2=--refresh-token terminal=false refresh=true".format(
            sys.executable, script
        ))
        return

    if current == "k2.7-code-highspeed":
        label = "HS"
        target = "k2.7-code"
    else:
        label = "L"
        target = "k2.7-code-highspeed"

    print_menu(current, label, target)


def refresh_token_cmd():
    try:
        refresh_token_via_webbridge()
        token = get_web_token()
        fetch_beta_status(token)
        print("Token 刷新成功", file=sys.stderr)
    except Exception as e:
        print(f"Token 刷新失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--toggle", action="store_true", help="切换 Beta 模式")
    parser.add_argument("--refresh-token", action="store_true", help="通过 WebBridge 刷新 Token")
    args = parser.parse_args()

    if args.toggle:
        try:
            toggle_beta_mode()
        except Exception as e:
            print(f"切换失败: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.refresh_token:
        refresh_token_cmd()
    else:
        main()
