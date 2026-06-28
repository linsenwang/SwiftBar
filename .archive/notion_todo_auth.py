#!/usr/bin/env python3
"""
Notion Todo 配置助手（适配 Notion API 2025-09-03 data_source 模式）

用途：
1. 引导用户在 Notion 创建 Integration 并获取 Token。
2. 用 token 列出用户可访问的 data sources，让用户选择/确认待办数据库。
3. 检查并自动补全 Name + Done 字段。
4. 保存 token 和 data_source_id 到本地配置文件。

配置文件：~/.swiftbar/notion_todo_credentials.json
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# 某些本地代理访问 api.notion.com 会触发 TLS EOF，直接连接更稳定
os.environ.setdefault("NO_PROXY", "api.notion.com")

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"
CREDENTIALS_DIR = Path.home() / ".swiftbar"
CREDENTIALS_PATH = CREDENTIALS_DIR / "notion_todo_credentials.json"


def load_credentials():
    if CREDENTIALS_PATH.exists():
        with open(CREDENTIALS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_credentials(data):
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    with open(CREDENTIALS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.chmod(CREDENTIALS_PATH, 0o600)
    print(f"配置已保存到: {CREDENTIALS_PATH}")


def notion_request(token, path, method="GET", body=None):
    url = f"{NOTION_API}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Notion API 错误 {e.code}: {err}")


def extract_uuid(s):
    """从字符串中提取/格式化 UUID。"""
    s = s.strip().split("?")[0].split("#")[0].rstrip("/")
    match = re.search(r"([a-f0-9]{32}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$", s)
    if match:
        raw = match.group(1).replace("-", "")
        return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    return None


def list_data_sources(token):
    """列出用户可访问的 data sources。"""
    sources = []
    cursor = None
    while True:
        body = {"filter": {"value": "data_source", "property": "object"}, "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        resp = notion_request(token, "/search", method="POST", body=body)
        sources.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return sources


def get_data_source(token, data_source_id):
    """获取指定 data source 的详情。"""
    return notion_request(token, f"/data_sources/{data_source_id}")


def ensure_data_source_schema(token, data_source_id):
    """检查 data source 是否有 Name 和 Done 字段，如果没有则尝试添加 Done。"""
    ds = get_data_source(token, data_source_id)
    props = ds.get("properties", {})

    name_prop = None
    done_prop = None
    for name, info in props.items():
        if info.get("type") == "title":
            name_prop = name
        if info.get("type") == "checkbox" and name.lower() in ("done", "完成"):
            done_prop = name

    if not name_prop:
        raise RuntimeError("数据库缺少标题（Name）字段，请先在 Notion 里添加一个 Title 列")

    if not done_prop:
        notion_request(
            token,
            f"/data_sources/{data_source_id}",
            method="PATCH",
            body={"properties": {"Done": {"checkbox": {}}}},
        )
        print("已自动为数据库添加 'Done' 复选框字段")
        done_prop = "Done"

    return name_prop, done_prop


def main():
    print("=== Notion Todo 配置助手 ===\n")
    creds = load_credentials()

    print("""
步骤 1：创建 Notion Integration
1. 打开 https://www.notion.so/my-integrations
2. 点击 '+ New integration' / 'New connection'
3. Name: SwiftBar Todo
4. Associated workspace: 选择你的工作区
5. Type: Internal
6. 点击 'Submit'
7. 复制 Token（以 ntn_ 或 secret_ 开头）
""")

    token = input("请输入 Integration Token: ").strip()
    if not (token.startswith("secret_") or token.startswith("ntn_")):
        print("Token 格式不对，应以 secret_ 或 ntn_ 开头", file=sys.stderr)
        sys.exit(1)

    try:
        user = notion_request(token, "/users/me")
        print(f"Token 验证通过，工作区: {user.get('name', 'Unknown')}\n")
    except Exception as e:
        print(f"Token 验证失败: {e}", file=sys.stderr)
        sys.exit(1)

    print("""
步骤 2：选择或创建待办数据库
在 Notion 里新建一个数据库（Table），命名为 'Tasks' 或 '待办'，
包含两列：
  - Name（标题列，默认就有）
  - Done（复选框列，脚本可以自动添加）

然后：
1. 点击数据库右上角 "..."
2. 选择 "Manage data sources" 或 "Copy data source ID"
3. 复制 data source ID（UUID 格式）
""")

    sources = list_data_sources(token)
    data_source_id = None

    if sources:
        print("检测到你可访问的 data sources：")
        for i, ds in enumerate(sources, 1):
            title = "无标题"
            if ds.get("title"):
                title = "".join([t.get("plain_text", "") for t in ds["title"]])
            print(f"  {i}. {title} ({ds['id']})")
        print("  0. 手动输入 data_source_id")
        choice = input("\n请选择（输入编号）: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(sources):
            data_source_id = sources[int(choice) - 1]["id"]
        else:
            ds_input = input("请输入 data_source_id 或数据库链接: ").strip()
            data_source_id = extract_uuid(ds_input)
            if not data_source_id:
                print("无法解析 UUID", file=sys.stderr)
                sys.exit(1)
    else:
        print("未检测到可访问的 data sources。")
        print("提示：请先在数据库页面点击 '...' → 'Add connections' → 添加 'SwiftBar Todo'")
        ds_input = input("请输入 data_source_id 或数据库链接: ").strip()
        data_source_id = extract_uuid(ds_input)
        if not data_source_id:
            print("无法解析 UUID", file=sys.stderr)
            sys.exit(1)

    try:
        name_prop, done_prop = ensure_data_source_schema(token, data_source_id)
        print(f"数据库字段检查通过: Name='{name_prop}', Done='{done_prop}'")
    except Exception as e:
        print(f"数据库检查失败: {e}", file=sys.stderr)
        print("提示：请确认 integration 已被添加到数据库的连接中", file=sys.stderr)
        sys.exit(1)

    creds.update({
        "token": token,
        "data_source_id": data_source_id,
        "name_property": name_prop,
        "done_property": done_prop,
    })
    save_credentials(creds)
    print("\n✅ 配置完成！现在可以安装 SwiftBar 插件了。")


if __name__ == "__main__":
    main()
