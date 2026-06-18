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
  （首次使用需通过 webbridge 从浏览器 localStorage 提取保存）
"""

import argparse
import json
import os
import sys
import urllib.request

WEB_TOKEN_PATH = os.path.expanduser("~/.kimi-code/credentials/kimi-web-token.json")
BETA_API_BASE = "https://www.kimi.com/apiv2/kimi.gateway.code.v1.BetaService"


def plugin_path() -> str:
    return os.path.abspath(sys.argv[0])


def get_web_token() -> str:
    with open(WEB_TOKEN_PATH, "r") as f:
        data = json.load(f)
    return data["access_token"]


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


def toggle_beta_mode():
    token = get_web_token()
    beta = fetch_beta_status(token)
    current = beta.get("beta", {}).get("selectedModel", "")
    target = "k2.7-code" if current == "k2.7-code-highspeed" else "k2.7-code-highspeed"
    select_beta_model(target, token)


def main():
    try:
        token = get_web_token()
        beta = fetch_beta_status(token)
        current = beta.get("beta", {}).get("selectedModel", "")
    except Exception:
        # 缺少 token 或 API 失败，显示问号并链接到 Beta 页面
        print("Kβ? | href=https://www.kimi.com/code/beta")
        return

    if current == "k2.7-code-highspeed":
        label = "H"
        target = "k2.7-code"
    else:
        label = "L"
        target = "k2.7-code-highspeed"

    script = plugin_path()
    print(
        f"{label} | bash={sys.executable} param1={script} param2=--toggle "
        f"terminal=false refresh=true"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--toggle", action="store_true", help="切换 Beta 模式")
    args = parser.parse_args()

    if args.toggle:
        try:
            toggle_beta_mode()
        except Exception as e:
            print(f"切换失败: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        main()
