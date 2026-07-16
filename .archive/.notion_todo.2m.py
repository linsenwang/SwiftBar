#!/usr/bin/env python3
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>

"""
SwiftBar 插件：Notion Todo
刷新频率：2 分钟（文件名中的 .2m.）
功能：在菜单栏显示未完成任务，支持添加、完成、隐藏/删除。

适配 Notion API 2025-09-03（data_source_id 模式）。

配置：
1. 先运行 ./notion_todo_auth.py 完成 Notion Integration 授权。
2. 将本文件复制到 SwiftBar 插件目录：
   cp notion_todo.2m.py "$HOME/Library/Application Support/SwiftBar/plugins/"
3. chmod +x "$HOME/Library/Application Support/SwiftBar/plugins/notion_todo.2m.py"

可选：在 notion_todo_credentials.json 中加入 "hidden_property": "Hidden"，
      并在 Notion 数据库中创建一个名为 Hidden 的 checkbox 属性，
      这样"删除"会变成"隐藏"，任务不会从 Notion 中移除，只是不在菜单中显示。
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# 某些本地代理访问 api.notion.com 会触发 TLS EOF，直接连接更稳定
os.environ.setdefault("NO_PROXY", "api.notion.com")

CREDENTIALS_PATH = Path.home() / ".swiftbar" / "notion_todo_credentials.json"
CACHE_PATH = Path.home() / ".swiftbar" / "notion_todo_cache.json"
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"

# 被认为是"长期任务/项目"的列表名（在菜单中分栏平铺显示）
LONG_TERM_LISTS = {"Tasks", "在做", "大作业", "寒假项目"}
SHORT_TERM_ORDER = ["My Day", "Important", "Planned", "Assigned to me"]

# 已完成菜单中直接显示的最近任务数量，其余折叠到"更早完成"
RECENT_COMPLETED_LIMIT = 5


def load_credentials():
    if CREDENTIALS_PATH.exists():
        with open(CREDENTIALS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def load_cache():
    """读取本地缓存的任务数据，用于 Notion API 失败时的离线兜底。"""
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"active": [], "completed": [], "last_sync": None, "error": None}


def save_cache(active, completed, error=None):
    """每次成功拉取后覆盖本地缓存。同步策略：以 Notion 为唯一数据源，本地只做只读兜底。"""
    data = {
        "active": active,
        "completed": completed,
        "last_sync": datetime.now(timezone.utc).isoformat(),
        "error": str(error) if error else None,
    }
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def notion_request(creds, path, method="GET", body=None):
    url = f"{NOTION_API}{path}"
    headers = {
        "Authorization": f"Bearer {creds['token']}",
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


def _not_hidden_filter(creds, base_filter):
    """如果配置了 hidden_property，则在 base_filter 上叠加 Hidden=false 条件。"""
    hidden_prop = creds.get("hidden_property")
    if not hidden_prop:
        return base_filter
    return {
        "and": [
            base_filter,
            {"property": hidden_prop, "checkbox": {"equals": False}},
        ]
    }


def get_active_tasks(creds):
    data_source_id = creds["data_source_id"]
    done_prop = creds.get("done_property", "Done")
    body = {
        "filter": _not_hidden_filter(
            creds,
            {"property": done_prop, "checkbox": {"equals": False}},
        ),
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        "page_size": 100,
    }
    resp = notion_request(creds, f"/data_sources/{data_source_id}/query", method="POST", body=body)
    return resp.get("results", [])


def get_completed_tasks(creds):
    data_source_id = creds["data_source_id"]
    done_prop = creds.get("done_property", "Done")
    body = {
        "filter": _not_hidden_filter(
            creds,
            {"property": done_prop, "checkbox": {"equals": True}},
        ),
        "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
        "page_size": 100,
    }
    resp = notion_request(creds, f"/data_sources/{data_source_id}/query", method="POST", body=body)
    return resp.get("results", [])


def get_task_title(task):
    props = task.get("properties", {})
    for info in props.values():
        if info.get("type") == "title":
            texts = info.get("title", [])
            return "".join([t.get("plain_text", "") for t in texts])
    return "无标题"


def get_task_types(task):
    """读取任务的 Task type（multi_select）列表。"""
    props = task.get("properties", {})
    for info in props.values():
        if info.get("type") == "multi_select" and info.get("multi_select"):
            return [opt.get("name", "") for opt in info.get("multi_select", []) if opt.get("name")]
    return []


def is_pure_long_term(task):
    """判断任务是否只被归类为长期任务/项目（用于排除菜单栏计数）。"""
    types = get_task_types(task)
    if not types:
        return False
    return all(t in LONG_TERM_LISTS for t in types)


def create_task(creds, title):
    data_source_id = creds["data_source_id"]
    done_prop = creds.get("done_property", "Done")
    name_prop = creds.get("name_property", "Name")
    hidden_prop = creds.get("hidden_property")
    properties = {
        name_prop: {"title": [{"text": {"content": title}}]},
        done_prop: {"checkbox": False},
    }
    if hidden_prop:
        properties[hidden_prop] = {"checkbox": False}
    body = {
        "parent": {"type": "data_source_id", "data_source_id": data_source_id},
        "properties": properties,
    }
    return notion_request(creds, "/pages", method="POST", body=body)


def complete_task(creds, page_id):
    done_prop = creds.get("done_property", "Done")
    body = {"properties": {done_prop: {"checkbox": True}}}
    return notion_request(creds, f"/pages/{page_id}", method="PATCH", body=body)


def uncheck_task(creds, page_id):
    done_prop = creds.get("done_property", "Done")
    body = {"properties": {done_prop: {"checkbox": False}}}
    return notion_request(creds, f"/pages/{page_id}", method="PATCH", body=body)


def archive_task(creds, page_id):
    """彻底删除（归档）任务；未配置 hidden_property 时的兜底行为。"""
    body = {"archived": True}
    return notion_request(creds, f"/pages/{page_id}", method="PATCH", body=body)


def hide_task(creds, page_id):
    """隐藏任务：在 Notion 中把 Hidden checkbox 设为 true，数据仍保留。"""
    hidden_prop = creds.get("hidden_property", "Hidden")
    body = {"properties": {hidden_prop: {"checkbox": True}}}
    return notion_request(creds, f"/pages/{page_id}", method="PATCH", body=body)


def remove_task(creds, page_id):
    """根据配置决定是隐藏还是归档。"""
    if creds.get("hidden_property"):
        return hide_task(creds, page_id)
    return archive_task(creds, page_id)


def escape_swiftbar(s):
    return s.replace("|", "\\|").replace("\n", " ")


def quote_path(s):
    if " " in s and not (s.startswith('"') and s.endswith('"')):
        return f'"{s}"'
    return s


def ask_input_dialog(prompt="请输入任务内容"):
    script = f'''
    tell application "System Events"
        activate
        set userInput to text returned of (display dialog "{prompt}" default answer "" buttons {{"取消", "确定"}} default button "确定" cancel button "取消")
    end tell
    return userInput
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except Exception:
        return None


def plugin_path():
    return Path(__file__).resolve()


def remove_menu_label(creds):
    """根据是否配置 hidden_property 返回菜单项的图标与文字。"""
    return ("👁 隐藏", "color=#888888") if creds.get("hidden_property") else ("🗑 删除", "")


def print_task_line(task, script_path, py_path, creds, indent=""):
    """输出单个任务行及其完成/隐藏/删除子菜单。"""
    page_id = task["id"]
    task_title = get_task_title(task)
    display_title = task_title if len(task_title) <= 40 else task_title[:37] + "..."
    display_title = escape_swiftbar(display_title)

    complete_cmd = f"bash={py_path} param1={script_path} param2=toggle param3={page_id} terminal=false refresh=true"
    remove_cmd = f"bash={py_path} param1={script_path} param2=delete param3={page_id} terminal=false refresh=true"

    label, extra = remove_menu_label(creds)
    extra_attr = f" | {extra}" if extra else ""

    print(f"{indent}☐ {display_title} | {complete_cmd}")
    print(f"{indent}-- ✅ 完成 | {complete_cmd}")
    print(f"{indent}-- {label} | {remove_cmd}{extra_attr}")


def print_completed_task_line(task, script_path, py_path, creds, indent="--"):
    """输出单个已完成任务行及其撤销/隐藏/删除子菜单。"""
    page_id = task["id"]
    task_title = get_task_title(task)
    display_title = task_title if len(task_title) <= 40 else task_title[:37] + "..."
    display_title = escape_swiftbar(display_title)

    uncheck_cmd = f"bash={py_path} param1={script_path} param2=uncheck param3={page_id} terminal=false refresh=true"
    remove_cmd = f"bash={py_path} param1={script_path} param2=delete param3={page_id} terminal=false refresh=true"

    submenu_indent = indent + "--"

    label, extra = remove_menu_label(creds)
    extra_attr = f" | {extra}" if extra else ""

    print(f"{indent}✅ {display_title} | {uncheck_cmd}")
    print(f"{submenu_indent}🔄 撤销 | {uncheck_cmd}")
    print(f"{submenu_indent}{label} | {remove_cmd}{extra_attr}")


def print_completed_group(tasks, script_path, py_path, creds, indent="--"):
    """输出一组已完成任务：先显示最近几条，剩余折叠到"更早完成"。"""
    recent = tasks[:RECENT_COMPLETED_LIMIT]
    older = tasks[RECENT_COMPLETED_LIMIT:]
    for task in recent:
        print_completed_task_line(task, script_path, py_path, creds, indent=indent)
    if older:
        print(f"{indent} 📂 更早完成 ({len(older)})")
        for task in older:
            print_completed_task_line(task, script_path, py_path, creds, indent=indent + "--")


def print_menu(creds, active_tasks, completed_tasks, using_cache=False, cache_error=None):
    short_term_count = sum(1 for task in active_tasks if not is_pure_long_term(task))
    title = f"📝 {short_term_count}" if short_term_count > 0 else "📝"
    print(f"{title} | refresh=true size=13")
    print("---")

    script_path = quote_path(str(plugin_path()))
    py_path = quote_path(sys.executable)
    print(f"➕ 添加任务 | bash={py_path} param1={script_path} param2=add terminal=false refresh=true")
    print("---")

    if using_cache:
        print("⚠️ 离线模式：使用本地缓存 | color=#FF9500")
        if cache_error:
            print(f"-- 同步失败: {escape_swiftbar(str(cache_error))} | color=#FF0000")
        last_sync = load_cache().get("last_sync")
        if last_sync:
            print(f"-- 上次同步: {escape_swiftbar(last_sync)} | color=#888888")
        print("---")

    if not active_tasks:
        print("暂无待办任务 | refresh=true")
        print("---")

    # 按 Task type 分组
    groups = {}
    ungrouped = []
    for task in active_tasks:
        types = get_task_types(task)
        if not types:
            ungrouped.append(task)
            continue
        for t in types:
            groups.setdefault(t, []).append(task)

    # 已完成任务同样按 Task type 分组
    completed_groups = {}
    completed_ungrouped = []
    for task in completed_tasks:
        types = get_task_types(task)
        if not types:
            completed_ungrouped.append(task)
            continue
        for t in types:
            completed_groups.setdefault(t, []).append(task)

    # 短期任务：按固定顺序平铺显示
    for list_name in SHORT_TERM_ORDER:
        if list_name not in groups:
            continue
        items = groups.pop(list_name)
        print(f"📌 {list_name} ({len(items)})")
        for task in items:
            print_task_line(task, script_path, py_path, creds, indent="--")
        if list_name in completed_groups:
            completed_items = completed_groups[list_name]
            print(f"-- ✅ 已完成 ({len(completed_items)})")
            print_completed_group(completed_items, script_path, py_path, creds, indent="----")
        print("---")

    # 长期任务/项目：分栏平铺，各列表之间不加横线
    long_term_groups = {k: v for k, v in groups.items() if k in LONG_TERM_LISTS}
    if long_term_groups:
        print(f"📁 长期项目 ({sum(len(v) for v in long_term_groups.values())})")
        for list_name in sorted(long_term_groups.keys()):
            items = long_term_groups[list_name]
            print(f"📂 {list_name} ({len(items)})")
            for task in items:
                print_task_line(task, script_path, py_path, creds, indent="--")
            if list_name in completed_groups:
                completed_items = completed_groups[list_name]
                print(f"-- ✅ 已完成 ({len(completed_items)})")
                print_completed_group(completed_items, script_path, py_path, creds, indent="----")
        print("---")

    # 剩下的其他分类（如果有）
    remaining = {k: v for k, v in groups.items() if k not in LONG_TERM_LISTS}
    for list_name in sorted(remaining.keys()):
        items = remaining[list_name]
        print(f"📂 {list_name} ({len(items)})")
        for task in items:
            print_task_line(task, script_path, py_path, creds, indent="--")
        if list_name in completed_groups:
            completed_items = completed_groups[list_name]
            print(f"-- ✅ 已完成 ({len(completed_items)})")
            print_completed_group(completed_items, script_path, py_path, creds, indent="----")
        print("---")

    if ungrouped:
        print(f"📂 未分类 ({len(ungrouped)})")
        for task in ungrouped:
            print_task_line(task, script_path, py_path, creds, indent="--")
        if completed_ungrouped:
            print(f"-- ✅ 已完成 ({len(completed_ungrouped)})")
            print_completed_group(completed_ungrouped, script_path, py_path, creds, indent="----")
        print("---")

    # 全局已完成任务栏
    if completed_tasks:
        print(f"✅ 已完成 ({len(completed_tasks)})")
        print_completed_group(completed_tasks, script_path, py_path, creds, indent="--")
        print("---")

    ds_id = creds.get("data_source_id", "")
    print(f"Notion 数据库 | href=https://notion.so/{ds_id.replace('-', '')}")


def action_add(creds):
    title = ask_input_dialog("请输入新任务")
    if not title:
        return
    try:
        create_task(creds, title)
    except Exception as e:
        print(f"添加失败: {e}")


def action_toggle(creds, page_id):
    try:
        complete_task(creds, page_id)
    except Exception as e:
        print(f"完成失败: {e}")


def action_uncheck(creds, page_id):
    try:
        uncheck_task(creds, page_id)
    except Exception as e:
        print(f"撤销失败: {e}")


def action_delete(creds, page_id):
    try:
        remove_task(creds, page_id)
    except Exception as e:
        label, _ = remove_menu_label(creds)
        print(f"{label}失败: {e}")


def main():
    creds = load_credentials()
    if not creds or not creds.get("token") or not creds.get("data_source_id"):
        print("📝 | refresh=true")
        print("---")
        print("未配置 | href=https://notion.so refresh=true")
        print("请先运行 notion_todo_auth.py | color=#FF0000")
        return

    if len(sys.argv) > 1:
        action = sys.argv[1]
        if action == "add":
            action_add(creds)
        elif action == "toggle" and len(sys.argv) >= 3:
            action_toggle(creds, sys.argv[2])
        elif action == "uncheck" and len(sys.argv) >= 3:
            action_uncheck(creds, sys.argv[2])
        elif action == "delete" and len(sys.argv) >= 3:
            action_delete(creds, sys.argv[2])
        return

    using_cache = False
    cache_error = None
    try:
        active_tasks = get_active_tasks(creds)
        completed_tasks = get_completed_tasks(creds)
        save_cache(active_tasks, completed_tasks)
    except Exception as e:
        cache = load_cache()
        active_tasks = cache.get("active", [])
        completed_tasks = cache.get("completed", [])
        cache_error = e
        using_cache = True

    try:
        print_menu(creds, active_tasks, completed_tasks, using_cache=using_cache, cache_error=cache_error)
    except Exception as e:
        print("📝 | refresh=true")
        print("---")
        print(f"错误: {escape_swiftbar(str(e))} | color=#FF0000")


if __name__ == "__main__":
    main()
