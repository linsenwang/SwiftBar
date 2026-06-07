#!/usr/bin/env python3
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>

"""
SwiftBar 插件: CapsWriter-Offline 状态监控与控制 (PM2 托管版)

功能:
- 菜单栏显示 CapsWriter 客户端运行状态
- 点击菜单项开始/结束语音识别（UDP 发送 START/STOP）
- 支持通过 PM2 启动/停止客户端进程
- 支持 UDP 控制录音（如果客户端启用了 udp_control）

安装:
1. 确保本文件在 SwiftBar 插件目录中
2. chmod +x capswriter.5s.py
3. SwiftBar 会自动识别

刷新频率: 5秒 (文件名中的 .5s. 控制)
"""

import json
import os
import subprocess
import socket
import sys
from typing import Optional

# ==================== 配置 ====================
CAPSWRITER_DIR = "/Users/yangqian/Downloads/local_asr/CapsWriter-Offline"
PM2_BIN = "/opt/homebrew/bin/pm2"
PM2_APP_NAME = "capswriter"
PYTHON = "/Users/yangqian/miniconda3/bin/python"
UDP_HOST = "127.0.0.1"
UDP_PORT = 6018
SCRIPT_PATH = os.path.abspath(__file__)
STATUS_FILE = os.path.join(CAPSWRITER_DIR, "status.json")
# ==============================================


def pm2_run(args: list[str]) -> subprocess.CompletedProcess:
    """运行 pm2 命令，返回结果"""
    return subprocess.run(
        [PM2_BIN] + args,
        capture_output=True, text=True, cwd=CAPSWRITER_DIR
    )


def is_client_running() -> bool:
    """检测 CapsWriter 客户端是否正在 PM2 中运行"""
    try:
        result = pm2_run(["jlist"])
        if result.returncode != 0:
            return False
        apps = json.loads(result.stdout)
        for app in apps:
            if app.get("name") == PM2_APP_NAME:
                status = app.get("pm2_env", {}).get("status")
                return status == "online"
        return False
    except Exception:
        return False


def get_recording_status() -> tuple[bool, float]:
    """
    读取 CapsWriter 录音状态

    Returns:
        (是否正在录音, 录音时长秒数)
    """
    try:
        import time
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            status = json.load(f)

        if not status.get("recording", False):
            return False, 0.0

        # 状态文件超过 30 秒未更新，认为已过期（客户端可能异常退出）
        if time.time() - status.get("timestamp", 0) > 30:
            return False, 0.0

        start_time = status.get("recording_start_time", 0)
        duration = time.time() - start_time if start_time > 0 else 0
        return True, duration
    except Exception:
        return False, 0.0


def get_client_pid() -> Optional[str]:
    """获取 PM2 托管的客户端进程 PID"""
    try:
        result = pm2_run(["jlist"])
        if result.returncode != 0:
            return None
        apps = json.loads(result.stdout)
        for app in apps:
            if app.get("name") == PM2_APP_NAME:
                pid = app.get("pid")
                return str(pid) if pid else None
        return None
    except Exception:
        return None


def send_udp_command(command: str) -> bool:
    """发送 UDP 控制命令 (START / STOP)"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(1)
            sock.sendto(command.encode('utf-8'), (UDP_HOST, UDP_PORT))
        return True
    except Exception:
        return False


def start_client() -> None:
    """通过 PM2 启动 CapsWriter 客户端"""
    try:
        # 先尝试启动已有的配置，如果失败则加载 ecosystem.config.js
        result = pm2_run(["start", PM2_APP_NAME])
        if result.returncode != 0:
            # 可能是首次运行，需要从配置文件加载
            config_path = os.path.join(CAPSWRITER_DIR, "ecosystem.config.js")
            result = pm2_run(["start", config_path])
        if result.returncode != 0:
            print(f"启动失败: {result.stderr}")
    except Exception as e:
        print(f"启动失败: {e}")


def stop_client() -> None:
    """通过 PM2 停止 CapsWriter 客户端"""
    try:
        pm2_run(["stop", PM2_APP_NAME])
    except Exception:
        pass


def toggle_recording() -> None:
    """模拟按下 F5 键（Dictation 键）来触发录音"""
    script = 'tell application "System Events" to key code 96'
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, check=False
        )
    except Exception:
        pass


def open_logs() -> None:
    """打开日志目录"""
    log_dir = os.path.join(CAPSWRITER_DIR, "logs")
    try:
        subprocess.run(["open", log_dir], check=False)
    except Exception:
        pass


def open_pm2_logs() -> None:
    """用 PM2 查看实时日志"""
    try:
        subprocess.Popen(
            [PM2_BIN, "logs", PM2_APP_NAME],
            cwd=CAPSWRITER_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
    except Exception:
        pass


def handle_action(action: str) -> None:
    """处理菜单点击动作"""
    if action == "toggle":
        toggle_recording()
    elif action == "udp_start":
        send_udp_command("START")
    elif action == "udp_stop":
        send_udp_command("STOP")
    elif action == "start_client":
        start_client()
    elif action == "stop_client":
        stop_client()
    elif action == "logs":
        open_logs()
    elif action == "pm2_logs":
        open_pm2_logs()


def main():
    # 如果带参数，执行动作后直接退出
    if len(sys.argv) > 1:
        handle_action(sys.argv[1])
        return

    running = is_client_running()

    if not running:
        # ===== 客户端未运行 =====
        print("⚪️ CW | color=#999999")
        print("---")
        print("CapsWriter 离线 (PM2)")
        print("---")
        print(f"▶️ PM2 启动客户端 | bash={SCRIPT_PATH} param1=start_client terminal=false refresh=true")
        print("---")
        print(f"打开项目目录 | bash=open param1={CAPSWRITER_DIR} terminal=false")
        return

    # ===== 客户端运行中 =====
    recording, duration = get_recording_status()

    if recording:
        # 正在录音：红色图标 + 时长
        print(f"🔴 CW {duration:.0f}s | color=#FF3B30")
    else:
        # 在线未录音：绿色图标
        print("🎤 CW | color=#34C759")

    print("---")
    print("CapsWriter 在线 (PM2)")
    if recording:
        print(f"正在录音... {duration:.1f} 秒")
    print("---")

    # 主要功能：开始/结束录音（模拟 F5）
    print("🔴 开始 / 结束录音 | bash={} param1=toggle terminal=false".format(SCRIPT_PATH))

    print("---")

    # UDP 控制（备用方式）
    print("⏺ UDP 开始录音 | bash={} param1=udp_start terminal=false".format(SCRIPT_PATH))
    print("⏹ UDP 停止录音 | bash={} param1=udp_stop terminal=false".format(SCRIPT_PATH))

    print("---")

    # 进程管理
    print("🛑 PM2 停止客户端 | bash={} param1=stop_client terminal=false refresh=true".format(SCRIPT_PATH))
    print("📋 PM2 查看日志 | bash={} param1=pm2_logs terminal=false".format(SCRIPT_PATH))
    print("---")
    print(f"📂 打开日志目录 | bash={SCRIPT_PATH} param1=logs terminal=false")
    print(f"📂 打开项目目录 | bash=open param1={CAPSWRITER_DIR} terminal=false")

    print("---")
    print("刷新 | refresh=true")


if __name__ == "__main__":
    main()
