#!/usr/bin/env python3
"""
将 Microsoft To Do 的任务列表同步到 Notion Tasks Tracker 数据库。

用法：
1. 把 Microsoft To Do 的 JSON 导出保存到 ms_todo_export.json
2. 运行 ./sync_ms_todo_to_notion.py

逻辑：
- 读取 ~/.swiftbar/notion_todo_credentials.json 获取 token 和 data_source_id
- 为每个列表名在 Notion 的 Task type 字段中添加选项
- 按任务标题去重，跳过已存在的任务
- 新任务默认 Status = "Not started"，Done = false，Task type = 列表名
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("NO_PROXY", "api.notion.com")

CREDENTIALS_PATH = Path.home() / ".swiftbar" / "notion_todo_credentials.json"
EXPORT_PATH = Path(__file__).parent / "ms_todo_export.json"
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"

# 被认为是"长期任务/项目"的列表名
LONG_TERM_LISTS = {"Tasks", "在做", "大作业", "寒假项目"}


def load_credentials():
    with open(CREDENTIALS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


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


def get_existing_tasks(token, data_source_id):
    """获取数据库中所有未完成的任务，用于去重。"""
    tasks = []
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        resp = notion_request(token, f"/data_sources/{data_source_id}/query", method="POST", body=body)
        tasks.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return tasks


def get_task_title(task):
    props = task.get("properties", {})
    for info in props.values():
        if info.get("type") == "title":
            texts = info.get("title", [])
            return "".join([t.get("plain_text", "") for t in texts]).strip()
    return ""


def get_task_types(task):
    """读取任务的 Task type（multi_select）列表。"""
    props = task.get("properties", {})
    for info in props.values():
        if info.get("type") == "multi_select" and info.get("multi_select"):
            return [opt.get("name", "") for opt in info.get("multi_select", []) if opt.get("name")]
    return []


def archive_task(token, page_id):
    """将任务归档（Notion 中的"删除"）。"""
    body = {"archived": True}
    return notion_request(token, f"/pages/{page_id}", method="PATCH", body=body)


def delete_tasks_by_list_name(token, data_source_id, list_name):
    """归档指定 Task type 的所有任务。"""
    tasks = get_existing_tasks(token, data_source_id)
    targets = [t for t in tasks if list_name in get_task_types(t)]
    if not targets:
        print(f"未找到 Task type 为 '{list_name}' 的任务")
        return 0
    for task in targets:
        title = get_task_title(task)
        archive_task(token, task["id"])
        print(f"已归档: {title}")
    print(f"共归档 {len(targets)} 个 '{list_name}' 任务")
    return len(targets)


def ensure_task_type_options(token, data_source_id, list_names):
    """确保 Task type 字段包含所有列表名作为选项。"""
    ds = notion_request(token, f"/data_sources/{data_source_id}")
    task_type = ds.get("properties", {}).get("Task type", {})
    if task_type.get("type") != "multi_select":
        print("警告: Task type 不是 multi_select，跳过选项更新", file=sys.stderr)
        return

    existing = {opt["name"] for opt in task_type.get("multi_select", {}).get("options", [])}
    new_options = []
    for name in list_names:
        if name not in existing:
            new_options.append({"name": name})

    if new_options:
        notion_request(
            token,
            f"/data_sources/{data_source_id}",
            method="PATCH",
            body={"properties": {"Task type": {"multi_select": {"options": new_options}}}},
        )
        print(f"已添加 {len(new_options)} 个 Task type 选项")


def create_task(token, data_source_id, title, list_name):
    body = {
        "parent": {"type": "data_source_id", "data_source_id": data_source_id},
        "properties": {
            "Task name": {"title": [{"text": {"content": title}}]},
            "Status": {"status": {"name": "Not started"}},
            "Done": {"checkbox": False},
            "Task type": {"multi_select": [{"name": list_name}]},
        },
    }
    return notion_request(token, "/pages", method="POST", body=body)


def main():
    # 命令行模式：按 Task type 归档（删除）指定列表的任务
    if len(sys.argv) > 1 and sys.argv[1] == "--delete-list":
        if len(sys.argv) < 3:
            print("用法: python3 sync_ms_todo_to_notion.py --delete-list <列表名>", file=sys.stderr)
            sys.exit(1)
        list_name = sys.argv[2]
        creds = load_credentials()
        delete_tasks_by_list_name(creds["token"], creds["data_source_id"], list_name)
        return

    if not EXPORT_PATH.exists():
        print(f"未找到导出文件: {EXPORT_PATH}", file=sys.stderr)
        print("请把 Microsoft To Do 的 JSON 导出保存为该文件", file=sys.stderr)
        sys.exit(1)

    with open(EXPORT_PATH, "r", encoding="utf-8") as f:
        ms_data = json.load(f)

    creds = load_credentials()
    token = creds["token"]
    data_source_id = creds["data_source_id"]

    # 收集所有列表名
    list_names = [name for name in ms_data.keys() if isinstance(ms_data[name], list)]
    ensure_task_type_options(token, data_source_id, list_names)

    # 获取已存在任务标题
    existing_tasks = get_existing_tasks(token, data_source_id)
    existing_titles = {get_task_title(t) for t in existing_tasks}

    created = 0
    skipped = 0
    for list_name, items in ms_data.items():
        if not isinstance(items, list):
            continue
        for item in items:
            title = str(item).strip()
            if not title:
                continue
            if title in existing_titles:
                skipped += 1
                continue
            try:
                create_task(token, data_source_id, title, list_name)
                created += 1
                existing_titles.add(title)
            except Exception as e:
                print(f"创建任务失败 '{title}': {e}", file=sys.stderr)

    print(f"\n同步完成: 新增 {created} 个任务，跳过 {skipped} 个重复任务")


if __name__ == "__main__":
    main()
