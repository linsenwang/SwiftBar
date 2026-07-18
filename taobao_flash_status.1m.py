#!/usr/bin/env python3
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>

"""
SwiftBar 插件: 淘宝闪购配送状态监控

功能:
- 默认暂停，点外卖后手动开启监控
- 自动查找微信里的淘宝闪购小程序窗口
- 截图并 OCR 识别当前配送状态
- 在菜单栏显示最新状态（如“商家已接单”“骑手正在送货”“已送达”等）
- 订单到达终态（已送达/已取消/配送异常）30 分钟后自动暂停，避免无意义截图
- 下拉菜单显示完整 OCR 文本和预计送达时间

前置依赖:
- tesseract (brew install tesseract tesseract-lang) —— Vision OCR 失败时的兜底
- Swift 编译器 (Xcode Command Line Tools，用于编译辅助程序)

安装:
1. 安装 SwiftBar: https://github.com/swiftbar/SwiftBar/releases
2. 将本文件复制到 SwiftBar 插件目录:
   cp taobao_flash_status.2m.py "$HOME/Library/Application Support/SwiftBar/plugins/"
3. 将辅助源码放到 .archive 目录（避免被 SwiftBar 识别成插件）:
   mkdir -p "$HOME/Library/Application Support/SwiftBar/plugins/.archive"
   cp taobao_flash_window_helper.swift taobao_flash_ocr_helper.swift \
     "$HOME/Library/Application Support/SwiftBar/plugins/.archive/"
4. 编译辅助程序:
   cd "$HOME/Library/Application Support/SwiftBar/plugins/.archive/"
   swiftc -O taobao_flash_window_helper.swift -o taobao_flash_window_helper
   swiftc -O taobao_flash_ocr_helper.swift -o taobao_flash_ocr_helper
5. 确保主插件可执行:
   chmod +x "$HOME/Library/Application Support/SwiftBar/plugins/taobao_flash_status.2m.py"
6. SwiftBar 会自动识别并显示在菜单栏

刷新频率: 1分钟（文件名中的 .1m. 控制）
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVE_DIR = os.path.join(SCRIPT_DIR, ".archive")
HELPER_BIN = os.path.join(ARCHIVE_DIR, "taobao_flash_window_helper")
OCR_HELPER_BIN = os.path.join(ARCHIVE_DIR, "taobao_flash_ocr_helper")
CACHE_PATH = os.path.join(ARCHIVE_DIR, "taobao_flash_status.json")
LOG_PATH = os.path.join(ARCHIVE_DIR, "taobao_flash_status.log")
STATE_PATH = os.path.join(ARCHIVE_DIR, "taobao_flash_status_state.json")
LOCK_PATH = os.path.join(ARCHIVE_DIR, "taobao_flash_status.lock")

# 文件锁有效期（秒）。SwiftBar 调度器可能把多次调用积压到同一秒执行，
# 加锁可以避免并发/连发的实例重复做截图+OCR 这种重活。
LOCK_TTL_SECONDS = 90

# 窗口查找配置
WINDOW_KEYWORD = "淘宝闪购"
WINDOW_OWNER = "WeChat"  # 留空则不限制应用

# OCR 配置
# 主 OCR 使用 macOS Vision 框架（识别率远高于 tesseract），失败时回退到 tesseract
TESSERACT_LANG = "chi_sim+eng"
TESSERACT_BIN = "/opt/homebrew/bin/tesseract"

# 运行控制配置
# 订单到达终态（已送达/已取消/配送异常）后，过多久自动暂停监控（分钟）
AUTO_PAUSE_AFTER_MINUTES = 30
# 终态列表
TERMINAL_STATUSES = {"已送达", "已取消", "配送异常"}

# 配送状态关键词（按优先级排序，越靠前越优先展示）
# 注意：这里匹配的是去除空格后的紧凑文本
# 原则：越接近配送完成、越代表当前动作的状态优先级越高
STATUS_PATTERNS = [
    ("已取消", r"订单已取消|已取消"),
    ("配送异常", r"配送异常|订单异常|配送失败"),
    ("已送达", r"已送达|订单已完成|送达成功"),
    ("配送中", r"骑[手士]正在为你送[货餐]|正在为你送[货餐]|正在送[货餐]|按序送货|配送中|正在配送"),
    ("骑手已取货", r"骑[手士]已取[货餐]|骑[手士]已到店"),
    ("骑手取货中", r"骑[手士]正在店内取货|正在店内取货.*?取货"),
    ("骑手已接单", r"骑[手士]已接单|骑[手士]正赶往商家|骑[手士]正在赶往商家|骑[手士]赶往商家|骑[手士]接单"),
    ("商家备货中", r"商家备货中|商家正在备[餐餐]|正在备[餐餐]|备货中"),
    ("商家已接单", r"商家已接单|商家已确认|已接单"),
    ("已预约", r"已预约|预约订单|预约中|预约配送|预约送达|指定时间|预计明天|预约时间"),
    ("待付款", r"待付款|待支付|请尽快支付"),
]

# 预计送达时间模式（捕获组内为要展示的时间文本）
ETA_PATTERNS = [
    r"(?:预计|预|预约时间)?\s*(\d{1,2}[：:]\d{2}\s*[-~]\s*\d{1,2}[：:]\d{2})",
    r"(?:预计|预|预约)?\s*(今天|明天|后天|\d{2}-\d{2})?\s*(\d{1,2}[：:]\d{2})",
    r"(?:预计|预)?\s*(\d{1,2}[：:]\d{2})",
]

# 距离/时间模式
DISTANCE_PATTERNS = [
    # 完整行: 距你Xkm Y分钟（固定一行出现）
    r"距你\s*([0-9.]+)\s*(?:公里|km)\s*(\d+)\s*分钟",
    # 单个距离/时间（兜底）
    r"距你\s*([0-9Oo]+)\s*(?:米|m)",
    r"距你\s*([0-9.]+)\s*(?:公里|km)",
    r"距商[家冢]\s*([0-9Oo]+)\s*(?:米|m)",
    r"距商[家冢]\s*([0-9.]+)\s*(?:公里|km)",
    r"大约?\s*(\d+)\s*分钟",
    r"(\d+)\s*分钟后?送达",
]

# 前方剩余单数模式
ORDER_COUNT_PATTERNS = [
    r"前方剩余\s*(\d+)\s*单",
    r"剩余\s*(\d+)\s*单",
    r"前面还有\s*(\d+)\s*单",
    r"还有\s*(\d+)\s*单",
    r"当前第\s*(\d+)\s*单",
]

BJT = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def log_debug(msg: str) -> None:
    """追加调试日志到 .archive/taobao_flash_status.log"""
    try:
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        now = datetime.now(BJT).strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{now}] {msg}\n")
    except Exception:
        pass


def is_lock_active() -> bool:
    """判断是否有近期实例正在执行重活。"""
    if not os.path.exists(LOCK_PATH):
        return False
    try:
        mtime = os.path.getmtime(LOCK_PATH)
        age = datetime.now().timestamp() - mtime
        return age < LOCK_TTL_SECONDS
    except Exception:
        return False


def touch_lock() -> None:
    """标记当前实例开始执行重活。"""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    with open(LOCK_PATH, "w", encoding="utf-8") as f:
        f.write(datetime.now(BJT).isoformat())


def remove_lock() -> None:
    """释放文件锁。"""
    try:
        os.remove(LOCK_PATH)
    except Exception:
        pass


def load_state() -> dict:
    """加载启停状态。默认未启用（避免无外卖时一直截图）。"""
    if not os.path.exists(STATE_PATH):
        return {"enabled": False, "completed_at": ""}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"enabled": False, "completed_at": ""}


def save_state(state: dict) -> None:
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def toggle_enabled() -> bool:
    """切换启用状态，用于菜单手动启停。手动开启时清除旧订单完成时间。"""
    state = load_state()
    new_enabled = not state.get("enabled", False)
    state["enabled"] = new_enabled
    if new_enabled:
        # 新一次监控开始，清除旧订单的完成时间，避免立刻被自动暂停
        state["completed_at"] = ""
    save_state(state)
    return new_enabled


def maybe_auto_pause(state: dict) -> dict:
    """如果订单已到达终态超过设定时间，自动暂停监控。"""
    completed_at = state.get("completed_at", "")
    if not completed_at:
        return state
    try:
        completed_dt = datetime.fromisoformat(completed_at)
        if datetime.now(BJT) - completed_dt > timedelta(minutes=AUTO_PAUSE_AFTER_MINUTES):
            state["enabled"] = False
            log_debug("auto-paused after terminal status")
    except Exception:
        pass
    return state


def ensure_helper() -> bool:
    """确保窗口查找辅助程序已编译。"""
    if os.path.exists(HELPER_BIN):
        return True
    swift_src = HELPER_BIN + ".swift"
    if not os.path.exists(swift_src):
        return False
    try:
        subprocess.run(
            ["swiftc", "-O", swift_src, "-o", HELPER_BIN],
            check=True,
            capture_output=True,
            timeout=120,
        )
        return os.path.exists(HELPER_BIN)
    except Exception:
        return False


def find_window() -> Optional[dict]:
    """通过辅助程序查找淘宝闪购小程序窗口。"""
    if not ensure_helper():
        raise RuntimeError("窗口查找辅助程序未找到且无法编译")

    args = [HELPER_BIN, "--find", WINDOW_KEYWORD]
    if WINDOW_OWNER:
        args.append(WINDOW_OWNER)

    result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def capture_window(window_id: int, output_path: str) -> None:
    """截图指定窗口（不包含阴影、不播放声音）。"""
    subprocess.run(
        ["screencapture", "-x", "-l", str(window_id), "-o", output_path],
        check=True,
        capture_output=True,
        timeout=15,
    )


def ocr_with_tesseract(image_path: str) -> str:
    """tesseract OCR 兜底方案。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        rel_img = os.path.join(tmpdir, "img.png")
        os.symlink(os.path.abspath(image_path), rel_img)
        proc = subprocess.run(
            [TESSERACT_BIN, "img.png", "out", "-l", TESSERACT_LANG],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            log_debug(f"tesseract error: {proc.stderr}")
            raise RuntimeError(f"tesseract 失败: {proc.stderr}")

        out_path = os.path.join(tmpdir, "out.txt")
        with open(out_path, "r", encoding="utf-8") as f:
            return f.read()


def ocr_image(image_path: str) -> str:
    """使用 macOS Vision 框架 OCR，失败时回退到 tesseract。"""
    if os.path.exists(OCR_HELPER_BIN):
        proc = subprocess.run(
            [OCR_HELPER_BIN, image_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            log_debug(f"vision ocr succeeded, length={len(proc.stdout)}")
            return proc.stdout
        log_debug(f"vision ocr failed or empty: rc={proc.returncode}, stderr={proc.stderr!r}")
    else:
        log_debug("vision ocr helper not found, falling back to tesseract")

    return ocr_with_tesseract(image_path)


def _compact(text: str) -> str:
    """移除 OCR 输出中汉字之间常见的空格，便于正则匹配。"""
    return re.sub(r"\s+", "", text)


def extract_status(text: str) -> str:
    """从 OCR 文本中提取配送状态。"""
    compact = _compact(text)
    for label, pattern in STATUS_PATTERNS:
        if re.search(pattern, compact):
            return label
    return ""


def extract_eta(text: str) -> str:
    """从 OCR 文本中提取预计送达时间。"""
    compact = _compact(text)
    for pattern in ETA_PATTERNS:
        m = re.search(pattern, compact)
        if m:
            parts = [g for g in m.groups() if g]
            return "".join(parts).replace(" ", "")
    return ""


def extract_distance(text: str) -> str:
    """从 OCR 文本中提取距离和剩余时间，合并为逗号分隔。"""
    compact = _compact(text)
    parts = []
    for pattern in DISTANCE_PATTERNS:
        m = re.search(pattern, compact)
        if m:
            groups = m.groups()
            if len(groups) == 2 and groups[0] and groups[1]:
                # 完整行: 距你Xkm Y分钟 → 6.3km,16m
                dist = groups[0].replace("O", "0").replace("o", "0")
                raw = f"{dist}km,{groups[1]}m"
                return raw
            raw = m.group(0)
            # 清理并简化显示：O->0，冢->家，分钟->m
            raw = raw.replace(" ", "").replace("距你", "").replace("O", "0").replace("o", "0").replace("冢", "家").replace("分钟", "m").replace("大约", "").replace("后送达", "").replace("送达", "").replace("公里", "km")
            if raw and raw not in parts:
                parts.append(raw)
    if parts:
        return ",".join(parts)
    return ""


def extract_order_count(text: str) -> str:
    """从 OCR 文本中提取前方剩余单数。"""
    compact = _compact(text)
    for pattern in ORDER_COUNT_PATTERNS:
        m = re.search(pattern, compact)
        if m:
            count = m.group(1)
            return f"剩{count}单"
    return ""


def load_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(data: dict) -> None:
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def format_menu_title(status: str, eta: str, distance: str, order_count: str) -> str:
    """生成菜单栏标题，保持简洁。优先级：距离 > 单数 > 预计时间。
    有具体状态时不再显示购物车图标，只有未识别/暂停时才显示图标用于点击。"""
    if status:
        title = status
    else:
        title = "🛒 未识别"

    extras = []
    if distance:
        extras.append(distance)
    elif order_count:
        extras.append(order_count)
    elif eta:
        extras.append(eta)

    if extras:
        title += f"({' '.join(extras)})"
    return title


def main():
    state = load_state()
    state = maybe_auto_pause(state)

    # 菜单里始终提供启停开关
    toggle_label = "暂停监控" if state.get("enabled", False) else "开启监控"

    if not state.get("enabled", False):
        # 暂停状态：不截图、不 OCR，菜单栏保持极简
        print(f"🛒 | font='Sarasa Mono SC' refresh=true size=13")
        print("---")
        print("外卖监控已暂停 | font='Sarasa Mono SC' size=13 refresh=true")
        print(f"{toggle_label} | refresh=true terminal=false bash={__file__} param1=--toggle")
        print("---")
        print(f"查看日志 | bash=/usr/bin/open param1={LOG_PATH} terminal=false")
        save_state(state)
        return

    cache = load_cache()
    error_msg = ""
    window_found = False
    from_cache = False
    ocr_text = ""
    status = ""
    eta = ""
    distance = ""
    order_count = ""
    window_title = ""

    # SwiftBar 的调度器不稳定，可能会把多次调用积压到同一秒执行。
    # 如果近期已经有实例在跑重活，本次直接读缓存，避免重复截图/OCR。
    if is_lock_active():
        log_debug("recent lock found, skipping heavy work and using cache")
        from_cache = True
        status = cache.get("status", "")
        eta = cache.get("eta", "")
        distance = cache.get("distance", "")
        order_count = cache.get("order_count", "")
        ocr_text = cache.get("ocr_text", "")
        window_title = cache.get("window_title", "")
    else:
        touch_lock()
        work_start = time.time()
        try:
            window = find_window()
            if window is None:
                log_debug("find_window returned None")
                raise RuntimeError("未找到淘宝闪购小程序窗口")

            window_found = True
            window_title = window.get("name", "")
            window_id = window.get("id")
            log_debug(f"window found: id={window_id}, title={window_title}")

            with tempfile.TemporaryDirectory() as tmpdir:
                png_path = os.path.join(tmpdir, "window.png")
                capture_window(window_id, png_path)
                log_debug(f"screenshot saved: {png_path}, size={os.path.getsize(png_path)}")
                ocr_text = ocr_image(png_path)
                log_debug(f"ocr length={len(ocr_text)}")

            status = extract_status(ocr_text)
            eta = extract_eta(ocr_text)
            distance = extract_distance(ocr_text)
            order_count = extract_order_count(ocr_text)
            log_debug(f"extracted: status={status!r}, eta={eta!r}, distance={distance!r}, order_count={order_count!r}")

            # 只有成功提取到状态时才更新缓存和时间戳
            if status:
                cache = {
                    "status": status,
                    "eta": eta,
                    "distance": distance,
                    "order_count": order_count,
                    "window_title": window_title,
                    "ocr_text": ocr_text,
                    "updated_at": datetime.now(BJT).isoformat(),
                }
                save_cache(cache)
                log_debug("cache updated")

                # 到达终态时记录完成时间，用于自动暂停
                if status in TERMINAL_STATUSES:
                    state["completed_at"] = datetime.now(BJT).isoformat()
                else:
                    state["completed_at"] = ""
            else:
                # 截图成功但无法识别状态：保留原缓存
                log_debug("no status extracted, falling back to cache")
                status = cache.get("status", "")
                eta = cache.get("eta", "")
                distance = cache.get("distance", "")
                order_count = cache.get("order_count", "")
                error_msg = "未从当前截图中识别到配送状态"
        except Exception as e:
            error_msg = str(e)
            log_debug(f"exception: {error_msg}\n{traceback.format_exc()}")
            # 出错时使用缓存
            from_cache = True
            status = cache.get("status", "")
            eta = cache.get("eta", "")
            distance = cache.get("distance", "")
            order_count = cache.get("order_count", "")
            ocr_text = cache.get("ocr_text", "")
            window_title = cache.get("window_title", "")
        finally:
            elapsed = time.time() - work_start
            log_debug(f"work elapsed {elapsed:.2f}s")
            remove_lock()

    save_state(state)

    # 菜单栏标题（末尾追加更新分钟）
    title = format_menu_title(status, eta, distance, order_count)
    if error_msg and not status:
        title = "🛒 未找到窗口"
    current_min = datetime.now(BJT).strftime("%M")
    print(f"{title}{current_min} | font='Sarasa Mono SC' refresh=true size=13")
    print("---")

    # 下拉详情
    if status:
        print(f"状态: {status} | font='Sarasa Mono SC' size=13 refresh=true")
    if eta:
        print(f"预计: {eta} | font='Sarasa Mono SC' size=13 refresh=true")
    if distance:
        print(f"距离: {distance} | font='Sarasa Mono SC' size=13 refresh=true")
    if order_count:
        print(f"单数: {order_count} | font='Sarasa Mono SC' size=13 refresh=true")

    updated_at = cache.get("updated_at", "")
    if updated_at:
        try:
            dt = datetime.fromisoformat(updated_at)
            time_str = dt.strftime("%H:%M")
            print(f"更新于 {time_str} | font='Sarasa Mono SC' size=12 color=#888888 refresh=true")
        except Exception:
            pass

    if window_title:
        print(f"窗口: {window_title} | font='Sarasa Mono SC' size=12 color=#888888 refresh=true")

    if from_cache:
        print("窗口未在前台，显示缓存状态 | font='Sarasa Mono SC' size=12 color=#888888 refresh=true")
    elif window_found and error_msg:
        print(f"{error_msg} | color=#888888 font='Sarasa Mono SC' size=12 refresh=true")
    elif error_msg:
        print(f"⚠️ {error_msg} | color=red font='Sarasa Mono SC' size=13 refresh=true")

    print("---")
    print(f"{toggle_label} | refresh=true terminal=false bash={__file__} param1=--toggle")
    print("刷新 | refresh=true terminal=false")

    # 完整 OCR 原文（折叠子菜单）
    if ocr_text:
        print("OCR 原文 | font='Sarasa Mono SC' size=13 refresh=true")
        for line in ocr_text.splitlines():
            line = line.strip()
            if line:
                # SwiftBar 子菜单以 -- 开头
                print(f"-- {line} | font='Sarasa Mono SC' size=12 refresh=true")

    print("---")
    print(f"查看日志 | bash=/usr/bin/open param1={LOG_PATH} terminal=false")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--toggle":
        toggle_enabled()
    else:
        main()
