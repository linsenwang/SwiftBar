#!/usr/bin/env python3
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>
# <swiftbar.refreshOnOpen>true</swiftbar.refreshOnOpen>

"""
SwiftBar 插件: BetterTouchTool 触发器（trigger）快速开关
刷新频率: 1 分钟（文件名里的 .1m. 控制）

功能:
- 菜单栏只显示已启用的数量，例如 🖱 9；总数看菜单里各分组标题上的 x/y
- 下拉菜单按 BTT 的分组列出触发器，✓ 已启用 / ✗ 已停用，点一下即切换
- 全局触发器按类别分组：Mouse Buttons 直接展开，其余类别收进子菜单（悬停展开）
- 绑定了特定应用的触发器（比如只在 Finder 里生效的）按应用分组，统一收进子菜单
- 切换后会用 get_trigger 回读一次确认，没生效会在菜单里标红
- 另附「全部启用 / 全部停用」

哪些不显示:
BTT 删除触发器并不是真删，而是丢进它自己的回收站：sqlite 里有个内置的
「Trash」应用（bundle id 是 BTT 自己生成的 BT.D），被删除的触发器都挂在它下面。
这些触发器照样能被 get_trigger 读到，所以得单独过滤，见 DELETED_APP_SCOPES。

分组配置:
- GROUP_LABELS: BTTTriggerClass → 菜单里显示的名字
- GROUP_ORDER:  全局分组在菜单里的先后顺序
- EXPANDED_GROUPS: 直接展开的组，其余都收进子菜单
- GLOBAL_APP_SCOPES / DELETED_APP_SCOPES: 见上面「哪些不显示」

为什么需要读 sqlite:
get_triggers 只返回「当前已启用」的触发器，停用的看不见；而且它不带 App 作用域
（停用的那批连 BTTBelongsToApp 字段都没有）。所以只读地查 BTT 的 sqlite：
ZBTTBASEENTITY 拿全部 UUID，Z_2APPS_GESTURES 拿每个触发器绑在哪个应用上。

原理:
- 读状态: tell application "BetterTouchTool" to get_trigger "<uuid>"
          JSON 里没有 BTTEnabled 或不为 0 就是已启用
- 开关:   update_trigger "<uuid>" json '{"BTTEnabled": 0|1}'
          这个键对应的就是 BTT 界面里触发器前面的勾，改完数据库里 ZISENABLED 会跟着变
"""

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

# -----------------------------------------------------------------------------
# 配置
# -----------------------------------------------------------------------------
APP = "BetterTouchTool"
SCRIPT_PATH = Path(__file__).resolve()
BTT_SUPPORT = Path.home() / "Library" / "Application Support" / "BetterTouchTool"

FONT = "font='Sarasa Mono SC'"
COLOR_ON = "#34C759"
COLOR_OFF = "#8E8E93"
COLOR_ERR = "#FF3B30"
COLOR_DIM = "#888888"

# 批量取回 JSON 时的分隔符，够怪就不会和内容撞上
SEP = "@@@BTT@@@"

# BTTTriggerClass → 菜单里显示的分组名
GROUP_LABELS = {
    "BTTTriggerTypeNormalMouse": "Mouse Buttons",
    "BTTTriggerTypeKeyboardShortcut": "Keyboard Shortcuts",
    "BTTTriggerTypeKeySequence": "Key Sequences",
    "BTTTriggerTypeTouchpadAll": "Trackpad",
    "BTTTriggerTypeTouchpadBuiltIn": "Trackpad",
    "BTTTriggerTypeTouchpadMagicTrackpad": "Trackpad",
    "BTTTriggerTypeTouchpadMagicTrackpad2": "Trackpad",
    "BTTTriggerTypeTouchpadWacom": "Trackpad",
    "BTTTriggerTypeTouchBarTrackpad": "Trackpad",
    "BTTTriggerTypeMagicMouse": "Magic Mouse",
    "BTTTriggerTypeTouchBar": "Touch Bar",
    "BTTTriggerTypeStreamDeck": "Stream Deck",
    "BTTTriggerTypeNotchBar": "Notch Bar",
    "BTTTriggerTypeFloatingMenu": "Floating Menu",
    "BTTTriggerTypeRecognizedDrawing": "Drawings",
    "BTTTriggerTypeDrawings": "Drawings",
    "BTTTriggerTypeSiriRemote": "Siri Remote",
    "BTTTriggerTypeMIDI": "MIDI",
    "BTTTriggerTypeGenericDevice": "Generic Device",
    "BTTTriggerTypeBTTRemote": "BTT Remote",
    "BTTTriggerTypeOtherTriggers": "Other Triggers",
}

# 分组在菜单里的先后顺序，没登记的排在最后（按名字）
GROUP_ORDER = [
    "Mouse Buttons",
    "Keyboard Shortcuts",
    "Key Sequences",
    "Trackpad",
    "Magic Mouse",
    "Touch Bar",
    "Stream Deck",
    "Notch Bar",
    "Floating Menu",
    "Drawings",
    "Siri Remote",
    "MIDI",
    "Generic Device",
    "BTT Remote",
    "Other Triggers",
]

# 直接展开的组，其余的收进子菜单
EXPANDED_GROUPS = {"Mouse Buttons"}

# 触发器绑定在哪个应用上（BTT 侧边栏的 App 分区）：
# - Global: 所有应用通用（没有 App 作用域的就是它），这类按触发器类别分组
# - Trash:  BTT 的回收站，被删除的触发器都堆在这，不显示
# - Recently Used: BTT 自己的桶，当普通应用处理
GLOBAL_APP_SCOPES = {None, "", "Global"}
DELETED_APP_SCOPES = {"Trash"}

FALLBACK_GROUP = "Other Triggers"


# -----------------------------------------------------------------------------
# 与 BTT 通信
# -----------------------------------------------------------------------------
def osascript(script: str, timeout: int = 20):
    """跑一段 AppleScript，返回 (stdout, 错误文本)。"""
    try:
        proc = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception as exc:
        return "", str(exc)
    if proc.returncode != 0:
        return proc.stdout, (proc.stderr or "").strip()
    return proc.stdout, ""


def btt_running() -> bool:
    """只查询不启动：告诉 osascript 别把 BTT 拉起来。"""
    out, _ = osascript(
        f'if application "{APP}" is running then return "1"\nreturn "0"', timeout=5
    )
    return out.strip() == "1"


def fetch_triggers(uuids):
    """一次 osascript 批量取回多个触发器的完整 JSON，返回 {uuid: dict}。"""
    uuids = list(uuids)
    if not uuids:
        return {}
    literals = ", ".join(f'"{u}"' for u in uuids)
    script = f'''tell application "{APP}"
	set out to ""
	repeat with u in {{{literals}}}
		try
			set out to out & (get_trigger (u as text)) & "{SEP}"
		on error
			set out to out & "{SEP}"
		end try
	end repeat
	return out
end tell'''
    out, _ = osascript(script)
    result = {}
    for uuid, chunk in zip(uuids, out.split(SEP)):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            data = json.loads(chunk)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("BTTUUID"):
            result[uuid] = data
    return result


def btt_db_rows(query: str):
    """只读地在 BTT 的 sqlite 上跑一条查询，返回行列表；打不开就返回空。"""
    try:
        files = [
            path
            for path in sorted(BTT_SUPPORT.glob("btt_data_store.version_*"))
            if not path.name.endswith(("-shm", "-wal"))
        ]
        if not files:
            return []
        con = sqlite3.connect(f"file:{files[-1]}?mode=ro", uri=True, timeout=5)
        try:
            return con.execute(query).fetchall()
        finally:
            con.close()
    except Exception:
        return []


def db_trigger_uuids():
    """所有触发器 UUID（含已停用的）。

    get_triggers 只给已启用的，停用的只能这样找。Z_ENT=9 是 Gesture 表：
    触发器本体 ZPARENT 为空，触发器下面的动作才带 ZPARENT；
    但也有一小部分触发器（Touch Bar、键盘快捷键）ZGESTURETYPE 不为正，
    所以两个条件取并集。
    """
    rows = btt_db_rows(
        "select ZUNIQUEIDENTIFIER from ZBTTBASEENTITY "
        "where Z_ENT = 9 and ZUNIQUEIDENTIFIER is not null "
        "and (ZPARENT is null or ZGESTURETYPE > 0)"
    )
    return [row[0] for row in rows if row[0]]


def db_app_scopes():
    """uuid → 绑定的应用名，返回 {uuid: App 名}。

    Z_2APPS_GESTURES 是 App → 触发器 的关联表，没有 App 作用域的触发器不在里面
    （在 BTT 界面里就算 Global）。被删除的触发器挂在 Trash 这个内置应用下。
    """
    rows = btt_db_rows(
        "select tr.ZUNIQUEIDENTIFIER, app.ZNAME from Z_2APPS_GESTURES j "
        "join ZBTTBASEENTITY app on app.Z_PK = j.Z_2GESTURES "
        "join ZBTTBASEENTITY tr on tr.Z_PK = j.Z_9APPS_GESTURES "
        "where tr.ZUNIQUEIDENTIFIER is not null"
    )
    return {row[0]: row[1] for row in rows if row[0]}


def all_triggers():
    """BTT 里所有触发器（含已停用、含已删除），返回 [(uuid, trigger json, App 名), ...]。

    已启用的走 get_triggers；停用的先由 sqlite 拿到 UUID，再批量 get_trigger 补上。
    App 名以 sqlite 为准：停用的那批 JSON 里没有 BTTBelongsToApp 字段。
    """
    triggers = {}
    out, err = osascript(f'tell application "{APP}" to get_triggers')
    if not err:
        try:
            data = json.loads(out)
        except Exception:
            data = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("BTTUUID") and not item.get("BTTIsPureAction"):
                    triggers[item["BTTUUID"]] = item

    missing = [uuid for uuid in db_trigger_uuids() if uuid not in triggers]
    triggers.update(fetch_triggers(missing))

    scopes = db_app_scopes()
    return [
        (uuid, trigger, scopes.get(uuid) or trigger.get("BTTBelongsToApp"))
        for uuid, trigger in triggers.items()
    ]


# -----------------------------------------------------------------------------
# 单个触发器的展示信息
# -----------------------------------------------------------------------------
NAME_KEYS = (
    "BTTTriggerTypeDescriptionReadOnly",
    "BTTTriggerName",
    "BTTName",
    "BTTTriggerTypeDescription",
)


def display_name(trigger: dict) -> str:
    """触发器显示成什么名字，取不到就退回 UUID 前 4 位。"""
    for key in NAME_KEYS:
        value = trigger.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f'未命名 #{trigger["BTTUUID"][:4].lower()}'


def group_name(trigger: dict) -> str:
    """触发器属于哪个类别（BTTTriggerClass），没登记过的类别直接用类名。"""
    cls = trigger.get("BTTTriggerClass")
    if isinstance(cls, str) and cls.strip():
        return GROUP_LABELS.get(cls, cls.strip().replace("BTTTriggerType", ""))
    return FALLBACK_GROUP


def scope_label(trigger: dict, app) -> str:
    """这一条归到哪个分组：绑了特定应用就按应用分，否则按触发器类别分。"""
    if app and app not in GLOBAL_APP_SCOPES:
        return str(app)
    return group_name(trigger)


# BTT 把方向键之类的键名放在 BTTLayoutIndependentActionChar 里
KEY_ALIASES = {
    "RIGHT": "→", "LEFT": "←", "UP": "↑", "DOWN": "↓",
    "SPACE": "空格", "RETURN": "回车", "TAB": "Tab", "ESCAPE": "Esc",
    "DELETE": "删除", "FORWARDDELETE": "前向删除",
}


def describe_action(trigger: dict) -> str:
    """触发器干了什么，用来区分同名触发器（比如三个 Button 3）。

    动作可能在 BTTActionsToExecute 里，也可能直接挂在触发器上（BTTIsPureAction）。
    """
    actions = trigger.get("BTTActionsToExecute")
    if not actions:
        actions = [trigger] if trigger.get("BTTPredefinedActionType") else []
    if not actions:
        return "无动作"

    first = actions[0]
    name = first.get("BTTPredefinedActionName")
    if not isinstance(name, str) or not name.strip():
        raw = first.get("BTTLayoutIndependentActionChar") or ""
        if not raw and first.get("BTTShortcutToSend"):
            raw = str(first["BTTShortcutToSend"])
        name = f"发送按键 {KEY_ALIASES.get(raw.upper(), raw)}".strip() if raw else "有动作"
    name = name.strip()
    if len(actions) > 1:
        name = f"{name} +{len(actions) - 1}"
    return name


def is_enabled(trigger: dict) -> bool:
    """BTT 只在停用时才写 BTTEnabled: 0，字段缺失即启用。"""
    if "BTTEnabled" not in trigger:
        return True
    try:
        return int(trigger["BTTEnabled"]) != 0
    except (TypeError, ValueError):
        return bool(trigger["BTTEnabled"])


def set_enabled(uuid: str, target: int):
    """写入开关并回读确认，返回 (是否成功, 错误文本)。"""
    payload = json.dumps({"BTTEnabled": target}).replace("\\", "\\\\").replace('"', '\\"')
    out, err = osascript(f'tell application "{APP}" to update_trigger "{uuid}" json "{payload}"')
    if err:
        return False, err
    after = fetch_triggers([uuid]).get(uuid)
    if after is None:
        return False, "写入后读不到这个触发器"
    if is_enabled(after) != bool(target):
        return False, "状态没有变化，可能被 BTT 拒绝了"
    return True, ""


# -----------------------------------------------------------------------------
# 输出
# -----------------------------------------------------------------------------
def esc(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def menu_item(title: str, *params) -> str:
    # SwiftBar 只按第一个 "|" 切分标题和参数，参数之间必须是空格，不能再出现 "|"
    return f"{esc(title)} | " + " ".join([FONT, *params])


def group_sort_key(label: str):
    """展开的组排最前，全局类别按 GROUP_ORDER，特定应用（没登记过的）垫底。"""
    if label in EXPANDED_GROUPS:
        return (0, 0, label)
    if label in GROUP_ORDER:
        return (1, GROUP_ORDER.index(label), label)
    return (2, 0, label)


def row_line(row: dict, indent: int = 0) -> str:
    """一个触发器的菜单行，indent=1 时挂到上一行（分组标题）的子菜单里。"""
    mark = "✓" if row["on"] else "✗"
    line = menu_item(
        f'{mark} {row["name"]} · {row["action"]}',
        f'color={COLOR_ON if row["on"] else COLOR_OFF}',
        f"bash={sys.executable}", f"param1={SCRIPT_PATH}", "param2=--toggle", f'param3={row["uuid"]}',
        "terminal=false", "refresh=true",
    )
    return "--" + line if indent else line


def print_menu():
    if not btt_running():
        print(f"🖱 未运行 | {FONT} size=13 refresh=true")
        print("---")
        print(f"BetterTouchTool 没有运行 | {FONT} size=13 color={COLOR_ERR} refresh=true")
        print("---")
        print(menu_item(
            "启动 BetterTouchTool",
            "bash=open", "param1=-a", f"param2={APP}", "terminal=false", "refresh=true",
        ))
        return

    entries = [
        (uuid, trigger, app)
        for uuid, trigger, app in all_triggers()
        # 被删除的都堆在 BTT 的回收站里，不显示
        if app not in DELETED_APP_SCOPES
    ]
    if not entries:
        print(f"🖱 没有可显示的触发器 | {FONT} size=13 color={COLOR_ERR} refresh=true")
        print("---")
        print(f"BTT 没运行，或者触发器都在回收站里 | {FONT} size=12 color={COLOR_ERR} refresh=true")
        return

    rows = [
        {
            "uuid": uuid,
            "group": scope_label(trigger, app),
            "name": display_name(trigger),
            "on": is_enabled(trigger),
            "action": describe_action(trigger),
            "order": trigger.get("BTTOrder") or 0,
        }
        for uuid, trigger, app in entries
    ]

    # 重名的（比如三个 Button 3）补一段 UUID，保证每行都能对上号
    name_counts = {}
    for row in rows:
        name_counts[row["name"]] = name_counts.get(row["name"], 0) + 1
    for row in rows:
        if name_counts[row["name"]] > 1:
            row["name"] = f'{row["name"]} #{row["uuid"][:4].lower()}'

    enabled = sum(1 for row in rows if row["on"])
    print(f"🖱 {enabled} | {FONT} size=13 refresh=true")
    print("---")

    by_group = {}
    for row in rows:
        by_group.setdefault(row["group"], []).append(row)

    for label, group_rows in sorted(by_group.items(), key=lambda kv: group_sort_key(kv[0])):
        group_rows.sort(key=lambda row: (row["order"], row["name"]))
        on = sum(1 for row in group_rows if row["on"])
        print(f"{esc(label)} · {on}/{len(group_rows)} | {FONT} size=12 color={COLOR_DIM}")
        expanded = label in EXPANDED_GROUPS
        for row in group_rows:
            print(row_line(row, indent=0 if expanded else 1))

    print("---")
    print(menu_item(
        "全部启用",
        f"bash={sys.executable}", f"param1={SCRIPT_PATH}", "param2=--all-on",
        "terminal=false", "refresh=true",
    ))
    print(menu_item(
        "全部停用",
        f"bash={sys.executable}", f"param1={SCRIPT_PATH}", "param2=--all-off",
        "terminal=false", "refresh=true",
    ))

    print("---")
    print(menu_item(
        "复制全部触发器清单",
        f"bash={sys.executable}", f"param1={SCRIPT_PATH}", "param2=--list",
        "terminal=false", "refresh=true",
    ))
    print(menu_item(
        "打开 BTT 设置",
        "bash=open", "param1=-a", f"param2={APP}", "terminal=false", "refresh=true",
    ))
    print(menu_item("刷新", "refresh=true"))


def copy_list_to_clipboard() -> int:
    """把所有触发器清单写进剪贴板（含已停用、已删除的，已删除的会标出来）。"""
    lines = []
    for uuid, trigger, app in sorted(
        all_triggers(),
        key=lambda item: (
            item[2] in DELETED_APP_SCOPES,
            not is_enabled(item[1]),
            item[1].get("BTTOrder") or 0,
        ),
    ):
        if app in DELETED_APP_SCOPES:
            state = "已删除"
        else:
            state = "已启用" if is_enabled(trigger) else "已停用"
        lines.append(
            f'{uuid}  {display_name(trigger)}  [{scope_label(trigger, app)}]  {state}  '
            f'→ {describe_action(trigger)}'
        )
    if not lines:
        print("没有拿到任何触发器（BTT 没运行，或者读不到数据）", file=sys.stderr)
        return 1
    subprocess.run(["/usr/bin/pbcopy"], input="\n".join(lines), text=True, check=False)
    return 0


# -----------------------------------------------------------------------------
# 入口
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--toggle", metavar="UUID", help="切换单个触发器")
    parser.add_argument("--all-on", action="store_true", help="启用所有触发器（已删除的除外）")
    parser.add_argument("--all-off", action="store_true", help="停用所有触发器（已删除的除外）")
    parser.add_argument("--list", action="store_true", help="把所有触发器清单复制到剪贴板")
    args = parser.parse_args()

    if args.list:
        return copy_list_to_clipboard()

    if args.toggle:
        if not btt_running():
            print("BetterTouchTool 没有运行", file=sys.stderr)
            return 1
        trigger = fetch_triggers([args.toggle]).get(args.toggle)
        if trigger is None:
            print(f"找不到触发器 {args.toggle}", file=sys.stderr)
            return 1
        ok, err = set_enabled(args.toggle, 0 if is_enabled(trigger) else 1)
        if not ok:
            print(f"切换失败: {err}", file=sys.stderr)
            return 1
        return 0

    if args.all_on or args.all_off:
        if not btt_running():
            print("BetterTouchTool 没有运行", file=sys.stderr)
            return 1
        target = 1 if args.all_on else 0
        failures = []
        for uuid, _, app in all_triggers():
            if app in DELETED_APP_SCOPES:
                continue
            ok, err = set_enabled(uuid, target)
            if not ok:
                failures.append(f"{uuid}: {err}")
        if failures:
            print("；".join(failures), file=sys.stderr)
            return 1
        return 0

    print_menu()
    return 0


if __name__ == "__main__":
    sys.exit(main())
