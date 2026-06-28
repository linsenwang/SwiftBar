#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>
"""
SwiftBar 吃药记录插件
- 菜单栏左侧显示沃克，右侧显示阿莫西林
- 下拉栏点击 +1 记录吃药，显示已吃数量、整板余数
- 自动显示 早/中/晚 服用情况
- 一键复制当前情况到剪贴板
文件名建议：medication.1h.py（每小时自动刷新）
"""

import json
import os
import subprocess
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
MEDS = {
    "wk": {
        "name": "沃克",
        "count": 20,           # 初始已吃数量
        "schedule": ["早", "晚"],
        "mod": 7,              # 一板数量
    },
    "amxl": {
        "name": "阿莫西林",
        "count": 30,           # 初始已吃数量
        "schedule": ["早", "中", "晚"],
        "mod": 10,
    },
}

PERIOD_HOURS = {
    "早": (4, 11),
    "中": (11, 17),
    "晚": (17, 4),  # 跨天：17:00 ~ 次日 04:00
}

# 全天吃药顺序（药品 key, 时段），按你期望的服用顺序排列
DOSE_SEQUENCE = [
    ("wk", "早"),
    ("amxl", "早"),
    ("amxl", "中"),
    ("wk", "晚"),
    ("amxl", "晚"),
]

STATE_FILE_NAME = "medication_state.json"


def remaining_slots(count, mod):
    """返回当前药板上还剩几格/几粒。"""
    r = count % mod
    return mod - r if r != 0 else 0

# ---------------------------------------------------------------------------
# 状态文件路径
# ---------------------------------------------------------------------------
def get_state_path():
    data_dir = os.environ.get("SWIFTBAR_PLUGIN_DATA_PATH")
    if data_dir:
        p = Path(data_dir)
    else:
        p = Path(__file__).resolve().parent
    p.mkdir(parents=True, exist_ok=True)
    return p / STATE_FILE_NAME


def load_state():
    path = get_state_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
            # 兼容旧数据结构
            for key, med in MEDS.items():
                if key not in state:
                    state[key] = {"count": med["count"], "doses": []}
                if "doses" not in state[key]:
                    state[key]["doses"] = []
            return state
        except Exception:
            pass

    # 首次创建时，把当前时段标记为已服用（贴合“现在是早上吃过之后”的初始状态）
    now = datetime.now().astimezone()
    cur_period, _ = current_period(now)
    return {
        key: {
            "count": med["count"],
            "doses": [now.isoformat()] if cur_period in med["schedule"] else [],
        }
        for key, med in MEDS.items()
    }


def save_state(state):
    path = get_state_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 时段工具
# ---------------------------------------------------------------------------
def current_period(now=None):
    """返回 (当前时段, 当前时段所属的参考日期)。"""
    if now is None:
        now = datetime.now().astimezone()
    h = now.hour
    today = now.date()
    if 4 <= h < 11:
        return "早", today
    elif 11 <= h < 17:
        return "中", today
    elif 17 <= h < 24:
        return "晚", today
    else:  # 0 <= h < 4，算前一天的晚
        return "晚", today - timedelta(days=1)


def period_window(ref_date, period):
    """返回某参考日期下某时段的起止时间（aware, 本地时区）。"""
    tz = datetime.now().astimezone().tzinfo
    if period == "早":
        start = datetime.combine(ref_date, time(4, 0)).replace(tzinfo=tz)
        end = datetime.combine(ref_date, time(11, 0)).replace(tzinfo=tz)
    elif period == "中":
        start = datetime.combine(ref_date, time(11, 0)).replace(tzinfo=tz)
        end = datetime.combine(ref_date, time(17, 0)).replace(tzinfo=tz)
    else:  # 晚：17:00 ~ 次日 04:00
        start = datetime.combine(ref_date, time(17, 0)).replace(tzinfo=tz)
        end = datetime.combine(ref_date + timedelta(days=1), time(4, 0)).replace(tzinfo=tz)
    return start, end


def is_taken_in_period(doses, ref_date, period):
    start, end = period_window(ref_date, period)
    for dose in doses:
        try:
            t = datetime.fromisoformat(dose)
        except Exception:
            continue
        if start <= t < end:
            return True
    return False


# ---------------------------------------------------------------------------
# 动作处理
# ---------------------------------------------------------------------------
def script_path():
    return os.environ.get("SWIFTBAR_PLUGIN_PATH", os.path.abspath(__file__))


def increment_med(key):
    state = load_state()
    if key not in state:
        state[key] = {"count": MEDS[key]["count"], "doses": []}
    state[key]["count"] += 1
    state[key]["doses"].append(datetime.now().astimezone().isoformat())
    # 只保留最近 90 天的记录，避免无限增长
    cutoff = (datetime.now().astimezone() - timedelta(days=90)).isoformat()
    state[key]["doses"] = [d for d in state[key]["doses"] if d > cutoff]
    save_state(state)


def forward_dose():
    """按 DOSE_SEQUENCE 顺序，把第一个未吃的项目标记为已吃。"""
    state = load_state()
    now = datetime.now().astimezone()
    _, ref_date = current_period(now)
    for key, period in DOSE_SEQUENCE:
        doses = state.get(key, {}).get("doses", [])
        if not is_taken_in_period(doses, ref_date, period):
            start, _ = period_window(ref_date, period)
            state[key]["count"] += 1
            state[key]["doses"].append((start + timedelta(minutes=1)).isoformat())
            # 只保留最近 90 天
            cutoff = (now - timedelta(days=90)).isoformat()
            state[key]["doses"] = [d for d in state[key]["doses"] if d > cutoff]
            save_state(state)
            return


def backward_dose():
    """撤销 DOSE_SEQUENCE 中最后一个已吃的项目。"""
    state = load_state()
    now = datetime.now().astimezone()
    _, ref_date = current_period(now)
    for key, period in reversed(DOSE_SEQUENCE):
        doses = state.get(key, {}).get("doses", [])
        start, end = period_window(ref_date, period)
        in_period = []
        for i, dose in enumerate(doses):
            try:
                t = datetime.fromisoformat(dose)
            except Exception:
                continue
            if start <= t < end:
                in_period.append(i)
        if in_period:
            idx = in_period[-1]
            state[key]["doses"].pop(idx)
            state[key]["count"] = max(0, state[key]["count"] - 1)
            save_state(state)
            return


def period_status_line(key, now=None):
    if now is None:
        now = datetime.now().astimezone()
    cur_period, ref_date = current_period(now)
    med = MEDS[key]
    state = load_state()
    doses = state.get(key, {}).get("doses", [])
    parts = []
    for p in med["schedule"]:
        taken = is_taken_in_period(doses, ref_date, p)
        symbol = "✅" if taken else "⬜"
        label = f"{p}{symbol}"
        if p == cur_period:
            label = f"▸{label}"
        parts.append(label)
    return f"{med['name']} {' '.join(parts)}"


def build_summary(state=None, now=None):
    if state is None:
        state = load_state()
    if now is None:
        now = datetime.now().astimezone()
    cur_period, ref_date = current_period(now)
    lines = []
    for key, med in MEDS.items():
        count = state.get(key, {}).get("count", med["count"])
        remaining = remaining_slots(count, med["mod"])
        taken_periods = [
            p for p in med["schedule"]
            if is_taken_in_period(state.get(key, {}).get("doses", []), ref_date, p)
        ]
        status = "".join(taken_periods)
        label = f"{med['name'][:1]}{status}" if status else med["name"][:1]
        lines.append(f"{label} {count} 剩{remaining}格")
    return "\n".join(lines)


def copy_current():
    summary = build_summary()
    try:
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, text=True)
        proc.communicate(summary)
    except Exception as e:
        print(f"复制失败：{e}")


# ---------------------------------------------------------------------------
# 主输出
# ---------------------------------------------------------------------------
def print_menu():
    state = load_state()
    now = datetime.now().astimezone()
    _, ref_date = current_period(now)

    # 菜单栏标题：只显示序列中最近一个未吃的项目
    next_dose = None
    for key, period in DOSE_SEQUENCE:
        doses = state.get(key, {}).get("doses", [])
        if not is_taken_in_period(doses, ref_date, period):
            next_dose = (key, period)
            break
    if next_dose:
        key, period = next_dose
        title = f"{MEDS[key]['name'][:1]}{period}"
    else:
        # 全部完成，显示下一轮第一个
        key, period = DOSE_SEQUENCE[0]
        title = f"{MEDS[key]['name'][:1]}{period}"
    print(
        f"{title} | bash=\"{script_path()}\" param1=forward terminal=false "
        f"refresh=true dropdown=false tooltip=点击前进，右键后退"
    )
    print("---")

    path = script_path()
    for key, med in MEDS.items():
        count = state.get(key, {}).get("count", med["count"])
        remaining = remaining_slots(count, med["mod"])
        taken_periods = [
            p for p in med["schedule"]
            if is_taken_in_period(state.get(key, {}).get("doses", []), ref_date, p)
        ]
        status = " ".join(taken_periods) if taken_periods else "未吃"
        abbr = med["name"][:1]
        print(
            f"{abbr} {count} 剩{remaining}格 {status} | "
            f'bash="{path}" param1=increment param2={key} terminal=false refresh=true'
        )

    print("---")
    print(
        f"复制 | "
        f'bash="{path}" param1=copy terminal=false refresh=true'
    )
    print(
        f"后退 | "
        f'bash="{path}" param1=backward terminal=false refresh=true'
    )


def main():
    # SwiftBar 动作参数通常通过 sys.argv 传入
    args = sys.argv[1:]
    if not args:
        # 兼容通过环境变量 param1 传参的情况
        env_param = os.environ.get("param1") or os.environ.get("PARAM1")
        if env_param:
            args = [env_param, os.environ.get("param2") or os.environ.get("PARAM2", "")]

    if args:
        action = args[0]
        if action == "increment" and len(args) >= 2 and args[1] in MEDS:
            increment_med(args[1])
        elif action == "copy":
            copy_current()
        elif action == "forward":
            forward_dose()
        elif action == "backward":
            backward_dose()
        # 动作执行后不需要输出菜单内容
        return

    print_menu()


if __name__ == "__main__":
    main()
