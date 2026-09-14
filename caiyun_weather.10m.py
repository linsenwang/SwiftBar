#!/usr/bin/env python3
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>

"""
SwiftBar 插件: 彩云天气
数据来源: 彩云天气 H5 内部 API (逆向获取, token: Y2FpeXVuIGFwaSB3ZWI)
位置: 118.0987, 24.4365 (厦门)
119.3111,26.0782 (福州)
刷新频率: 10分钟

数据采集: 可把与体感温度相关的实时数据（温度/湿度/风速等环境量
+ 官方体感温度）追加到 .archive/caiyun_apparent_log.jsonl，供回归拟合
体感温度公式使用。采集默认关闭（LOG_APPARENT_ENABLED=False），冬天校准
低温段公式时可再打开。
"""

import json
import urllib.request
import re
import random
import base64
import os
from datetime import datetime, timedelta, timezone

# 配置
# -----------------------------------------------------------------------------
# TOKEN 来源说明:
#   这个 token 是从彩云天气 H5 页面 (https://www.caiyunapp.com/h5/) 逆向抓包
#   得到的。H5 页面除了走 /api/ 反向代理（需要 ticket）外，还会直接发一个
#   .jsonp 请求到 api.caiyunapp.com，用的就是这个硬编码 token:
#
#       Y2FpeXVuIGFwaSB3ZWI   (Base64 解码后是 "caiyun api w")
#
#   抓包方法（token 失效后重新获取）:
#   1. 打开 https://www.caiyunapp.com/h5/ 并允许定位（或让它 fallback 到默认坐标）
#   2. 打开浏览器 DevTools -> Network
#   3. 过滤 "api.caiyunapp.com/v2/"
#   4. 找到类似这样的请求:
#       https://api.caiyunapp.com/v2/XXXXXXXX/116.4074,39.9042/forecast.jsonp?...
#      其中 XXXXXXXX 就是 token
#   5. 把这个 token 填到下面的 TOKEN 变量里即可
#
#   备选方案: 如果 H5 的 token 彻底失效，可以去彩云开放平台
#   https://platform.caiyunapp.com/ 注册申请自己的 token，每天有免费额度，
#   替换掉下面的 TOKEN 即可。
# -----------------------------------------------------------------------------
TOKEN = "Y2FpeXVuIGFwaSB3ZWI"
# LNG, LAT = "118.0987", "24.4365" #思明
LNG, LAT = "118.1149", "24.4394" #学公
# LNG, LAT = "119.3111", "26.0782" #福州
API_URL = f"https://api.caiyunapp.com/v2/{TOKEN}/{LNG},{LAT}/weather.jsonp"

import struct
import zlib


def _png_chunk(chunk_type, data):
    chunk = chunk_type + data
    crc = zlib.crc32(chunk) & 0xffffffff
    return struct.pack(">I", len(data)) + chunk + struct.pack(">I", crc)


def _encode_png(rgba_pixels, width, height, ppi=72):
    """纯标准库 PNG 编码器（RGBA 8bit），支持通过 pHYs 块设置 PPI"""
    raw = b""
    for y in range(height):
        raw += b"\x00"
        for x in range(width):
            raw += bytes(rgba_pixels[y * width + x])
    compressed = zlib.compress(raw)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    # pHYs 块：声明物理像素密度，macOS/SwiftBar 据此按实际尺寸渲染
    ppm = int(round(ppi / 0.0254))  # pixels per meter
    phys = _png_chunk(b"pHYs", struct.pack(">IIB", ppm, ppm, 1))
    idat = _png_chunk(b"IDAT", compressed)
    iend = _png_chunk(b"IEND", b"")
    return sig + ihdr + phys + idat + iend


def _rain_color(val):
    """根据降雨强度返回 (r, g, b, a)，暖色调：黄→橙→红，参考彩云官方配色"""
    if val < 0.05:
        # 接近无雨：浅黄绿，低透明度
        return (200, 230, 170, 140)
    elif val < 0.5:
        # 小雨：浅黄绿 → 黄色 → 浅橙
        t = (val - 0.05) / 0.45
        r = int(200 + (255 - 200) * t)
        g = int(230 + (190 - 230) * t)
        b = int(170 + (70 - 170) * t)
        return (r, g, b, 230)
    elif val < 2.5:
        # 中雨：浅橙 → 橙色
        t = (val - 0.5) / 2.0
        r = 255
        g = int(190 + (130 - 190) * t)
        b = int(70 + (30 - 70) * t)
        return (r, g, b, 230)
    elif val < 8.0:
        # 大雨：橙色 → 红色
        t = (val - 2.5) / 5.5
        r = int(255 + (230 - 255) * t)
        g = int(130 + (50 - 130) * t)
        b = int(30 + (40 - 30) * t)
        return (r, g, b, 230)
    elif val < 15.9:
        # 暴雨：红色 → 深红
        t = (val - 8.0) / 7.9
        r = int(230 + (180 - 230) * t)
        g = int(50 + (20 - 50) * t)
        b = int(40 + (20 - 40) * t)
        return (r, g, b, 230)
    else:
        # 大暴雨：深红
        return (160, 20, 20, 230)


def render_rain_chart(precip_2h):
    if not precip_2h or len(precip_2h) < 60 or max(precip_2h) < 0.05:
        return None
    # 原始数据最多 120 个分钟级数据点，线性插值到 240 个点
    CHART_POINTS = 240
    CHART_HEIGHT = 60
    SCALE = 2               # 2x 渲染，配合 144 PPI 在 Retina 下更清晰且尺寸不变
    raw = precip_2h[:120]
    values = []
    for i in range(CHART_POINTS):
        f = i / (CHART_POINTS - 1.0) * (len(raw) - 1)
        i0 = int(f)
        i1 = min(i0 + 1, len(raw) - 1)
        t = f - i0
        values.append(raw[i0] * (1 - t) + raw[i1] * t)
    bar_w = 1 * SCALE
    gap = 0
    pad_left = 0
    pad_bottom = 2 * SCALE
    usable_h_offset = 8 * SCALE
    W = CHART_POINTS * SCALE
    H = CHART_HEIGHT * SCALE
    # 全透明背景
    pixels = [(0, 0, 0, 0)] * (W * H)
    height_threshold = 0.4
    max_val = max(max(values), height_threshold) if max(values) > 0 else height_threshold
    for i, val in enumerate(values):
        x0 = pad_left + i * (bar_w + gap)
        x1 = x0 + bar_w
        bar_h = max(2 * SCALE, int((val / max_val) * (H - usable_h_offset)))
        y0 = H - bar_h - pad_bottom
        y1 = H - pad_bottom
        color = _rain_color(val)
        for y in range(y0, y1):
            for x in range(x0, x1):
                if 0 <= x < W and 0 <= y < H:
                    pixels[y * W + x] = color

    # 固定阈值横线：0.1mm/h（小雨下限）和 0.3mm/h
    line_color = (160, 160, 160, 140)
    for threshold in (0.1, 0.3):
        if threshold <= max_val:
            ly = H - pad_bottom - int((threshold / max_val) * (H - usable_h_offset))
            if 0 <= ly < H:
                for x in range(W):
                    pixels[ly * W + x] = line_color

    png_data = _encode_png(pixels, W, H, ppi=72 * SCALE)
    return base64.b64encode(png_data).decode()


def render_rain_ansi(precip_2h):
    """用 ANSI 24-bit 颜色代码绘制降雨柱状图（纯文本）"""
    if not precip_2h or len(precip_2h) < 60:
        return None
    values = [precip_2h[i] for i in range(0, 120, 10)]
    bars = ""
    for val in values:
        r, g, b, _ = _rain_color(val)
        bars += f"\x1b[38;2;{r};{g};{b}m█\x1b[0m"
    return bars


def format_hourly_line(i, hourly_temp, hourly_skycon, hourly_precip, hourly_wind, hourly_aqi, now,
                       hourly_humidity=None, show_apparent=False):
    """格式化单条逐小时预报行"""
    h_temp = hourly_temp[i]
    h_sky = hourly_skycon[i] if i < len(hourly_skycon) else {}
    h_precip = hourly_precip[i] if i < len(hourly_precip) else {}
    h_wind = hourly_wind[i] if i < len(hourly_wind) else {}
    h_aqi = hourly_aqi[i] if i < len(hourly_aqi) else {}
    h_humidity = hourly_humidity[i] if hourly_humidity and i < len(hourly_humidity) else {}

    dt_str = h_temp.get("datetime", "")
    try:
        h_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        if h_dt.date() == now.date() and h_dt.hour == now.hour:
            time_label = "现在"
        elif h_dt.date() == now.date():
            time_label = h_dt.strftime("%H:%M")
        else:
            time_label = h_dt.strftime("%m-%d %H:%M")
    except Exception:
        time_label = "--:--"

    temp_val = h_temp.get("value", 0)
    precip_val = h_precip.get("value", 0)
    p_icon, p_skycon_key = precip_level(precip_val)

    sky_raw = h_sky.get("value", "")
    # 如果 API 返回泛化的 RAIN，根据降水量细化成具体等级
    if sky_raw == "RAIN" and precip_val > 0.05 and p_skycon_key:
        sky_raw = p_skycon_key

    sky_val = SKYCON_MAP.get(sky_raw, sky_raw)
    sky_icon = sky_val.split()[0] if " " in sky_val else "🌡️"
    sky_text = sky_val.split()[-1] if " " in sky_val else sky_val
    # precip_str = f"{p_icon}{precip_val:.1f}mm" if precip_val > 0.05 and p_icon else ""
    precip_str = f"{precip_val:.1f}mm" if precip_val > 0.05 and p_icon else ""

    # 无雨且要求显示体感温度时，计算并追加体感温度
    no_rain = precip_val < 0.05
    apparent_str = ""
    if show_apparent and no_rain:
        at = apparent_temperature(
            temp_val,
            h_humidity.get("value"),
            h_wind.get("speed", 0),
        )
        if at is not None:
            apparent_str = f"{at:.1f}°"

    parts = [f"{sky_icon} {time_label} {temp_val:.1f}°"]
    if apparent_str:
        parts.append(apparent_str)
    parts.append(sky_text)
    if precip_str:
        parts.append(precip_str)
    return " ".join(parts)


def format_daily_line(i, daily_temp, daily_skycon, daily_aqi, daily_wind, today, weekdays):
    """格式化单条天级预报行"""
    t = daily_temp[i]
    s = daily_skycon[i] if i < len(daily_skycon) else {}
    a = daily_aqi[i] if i < len(daily_aqi) else {}
    w = daily_wind[i] if i < len(daily_wind) else {}

    dt = today + timedelta(days=i)
    wd = weekdays[dt.weekday()]
    date_str = dt.strftime("%m-%d")
    label = "今天" if i == 0 else ("明天" if i == 1 else f"{wd}")

    t_max = t.get("max", 0)
    t_min = t.get("min", 0)
    sky = SKYCON_MAP.get(s.get("value", ""), s.get("value", ""))
    sky_icon = sky.split()[0] if " " in sky else "🌡️"

    line = f"{sky_icon} {label} {date_str} {t_min:.0f}°~{t_max:.0f}° {sky.split()[-1] if ' ' in sky else sky}"
    return line


# 降雨等级（按小时降水强度 mm/h） → 返回 (图标, 映射用的 skycon_key)
def apparent_temperature(temp_c, humidity_frac, wind_speed_ms):
    """体感温度（2026-08 回归拟合自彩云官方，228 个样本）。

    公式: at = 1.04*T + 0.2*e - 0.18*V - 2.7
          e = RH * 6.105*exp(17.27*T/(237.7+T))  (实际水汽压 hPa, Magnus)
    拟合精度: MAE≈0.02°C，100% 样本误差 ≤0.1°C（官方值本身只精确到 0.1），
    实测覆盖 T 25~39°C，24.4°C 夜间样本亦吻合。
    低温（T<10°C）官方行为无数据验证，暂保留标准风寒公式。
    """
    import math
    try:
        rh = max(0.0, min(1.0, float(humidity_frac)))  # 0-1
        t = float(temp_c)
        ws = max(0.0, float(wind_speed_ms))
    except (TypeError, ValueError):
        return None

    if t >= 10:
        # 拟合公式（含湿度经水汽压 e 的指数型影响 + 风速线性降温）
        e = rh * 6.105 * math.exp(17.27 * t / (237.7 + t))
        return 1.04 * t + 0.2 * e - 0.18 * ws - 2.7
    else:
        # 低温：标准风寒公式（单位 °C / m/s）
        return 13.12 + 0.6215 * t - 11.37 * (ws ** 0.16) + 0.3965 * t * (ws ** 0.16)


def precip_level(val):
    if val < 0.1:
        return "", ""
    elif val <= 2.5:
        return "💧", "LIGHT_RAIN"
    elif val <= 8.0:
        return "💦", "MODERATE_RAIN"
    elif val <= 15.9:
        return "🌧️", "HEAVY_RAIN"
    else:
        return "⛈️", "STORM_RAIN"


# 天气现象映射
SKYCON_MAP = {
    "CLEAR_DAY": "☀️ 晴",
    "CLEAR_NIGHT": "🌙 晴",
    "PARTLY_CLOUDY_DAY": "⛅ 多云",
    "PARTLY_CLOUDY_NIGHT": "🌤️ 多云",
    "CLOUDY": "☁️ 阴",
    "LIGHT_RAIN": "💧 小雨",
    "MODERATE_RAIN": "💦 中雨",
    "HEAVY_RAIN": "🌧️ 大雨",
    "STORM_RAIN": "⛈️ 暴雨",
    "LIGHT_SNOW": "🌨️ 小雪",
    "MODERATE_SNOW": "🌨️ 中雪",
    "HEAVY_SNOW": "🌨️ 大雪",
    "STORM_SNOW": "❄️ 暴雪",
    "WIND": "💨 大风",
    "FOG": "🌫️ 雾",
    "HAZE": "😷 霾",
    "RAIN": "🌧️ 雨",
}

# SKYCON_MAP = {
#     "CLEAR_DAY": "晴",
#     "CLEAR_NIGHT": "晴",
#     "PARTLY_CLOUDY_DAY": "多云",
#     "PARTLY_CLOUDY_NIGHT": "多云",
#     "CLOUDY": "阴",
#     "LIGHT_RAIN": "小雨",
#     "MODERATE_RAIN": "中雨",
#     "HEAVY_RAIN": "大雨",
#     "STORM_RAIN": "暴雨",
#     "LIGHT_SNOW": "小雪",
#     "MODERATE_SNOW": "中雪",
#     "HEAVY_SNOW": "大雪",
#     "STORM_SNOW": "暴雪",
#     "WIND": "大风",
#     "FOG": "雾",
#     "HAZE": "霾",
#     "RAIN": "雨",
# }

# AQI 等级映射
def aqi_level(aqi):
    if aqi <= 50:
        return "🟢 优"
    elif aqi <= 100:
        return "🟡 良"
    elif aqi <= 150:
        return "🟠 轻度"
    elif aqi <= 200:
        return "🔴 中度"
    elif aqi <= 300:
        return "🟣 重度"
    else:
        return "⚫ 严重"

# 风向角度转方向
def wind_direction(deg):
    dirs = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
    idx = round(deg / 45) % 8
    return dirs[idx]

# 风速等级描述 (m/s) — 蒲福风级
def wind_desc(speed):
    if speed < 0.3:
        return "静风"
    elif speed < 1.6:
        return "软风"
    elif speed < 3.4:
        return "轻风"
    elif speed < 5.5:
        return "微风"
    elif speed < 8.0:
        return "和风"
    elif speed < 10.8:
        return "清风"
    elif speed < 13.9:
        return "强风"
    elif speed < 17.2:
        return "疾风"
    elif speed < 20.8:
        return "大风"
    elif speed < 24.5:
        return "烈风"
    elif speed < 28.5:
        return "狂风"
    elif speed < 32.7:
        return "暴风"
    else:
        return "飓风"


def fetch_weather():
    url = f"{API_URL}?hourlysteps=120&random={random.random()}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Referer": "https://www.caiyunapp.com/h5/",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 体感温度数据采集（供后续回归拟合）
# ---------------------------------------------------------------------------
BJT = timezone(timedelta(hours=8))  # 北京时间 (UTC+8)
ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".archive")
APPARENT_LOG_PATH = os.path.join(ARCHIVE_DIR, "caiyun_apparent_log.jsonl")
LOG_APPARENT_ENABLED = False  # 采集开关：默认关闭；冬天想校准低温段公式时再打开
LOG_INTERVAL_MINUTES = 30  # 采集最小间隔：距上一条记录不足该分钟数则跳过


def log_apparent_data(data):
    """把与体感温度相关的实时数据追加到日志，供后续回归拟合使用。

    记录 realtime 的完整环境量（温度/湿度/风速风向/云量/辐射/气压/能见度等）
    + 官方体感温度（作为回归目标 y）+ 当前估算值（作为基线对比）。
    LOG_APPARENT_ENABLED 为 False 时不采集（默认关闭）。
    节流规则（两者都检查）:
    - 与日志最后一条记录的 server_time 相同 → 跳过（同一份 API 数据）
    - 距最后一条记录不足 LOG_INTERVAL_MINUTES 分钟 → 跳过（避免记录过密）
    """
    if not LOG_APPARENT_ENABLED:
        return
    result = data.get("result", {}) or {}
    rt = result.get("realtime", {}) or {}
    server_time = data.get("server_time", 0)
    if not rt or not server_time:
        return

    # 读日志尾部最后一条有效记录，判断是否需要跳过
    if os.path.exists(APPARENT_LOG_PATH):
        with open(APPARENT_LOG_PATH, "rb") as f:
            f.seek(0, 2)  # EOF
            size = f.tell()
            if size > 0:
                f.seek(max(0, size - 512))
                tail = f.read().decode("utf-8", errors="ignore").strip().split("\n")
                last_rec = None
                for line in reversed(tail):
                    if not line.strip():
                        continue
                    try:
                        last_rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    break
                if last_rec:
                    if last_rec.get("server_time") == server_time:
                        return  # 同一份 API 数据，不重复记录
                    try:
                        last_dt = datetime.strptime(last_rec.get("ts", ""), "%Y-%m-%dT%H:%M:%S%z")
                        if datetime.now(BJT) - last_dt < timedelta(minutes=LOG_INTERVAL_MINUTES):
                            return  # 距上一条记录太近，跳过
                    except ValueError:
                        pass

    wind = rt.get("wind", {}) or {}
    temp = rt.get("temperature", 0)
    humidity = rt.get("humidity", 0)
    wind_speed = wind.get("speed", 0)
    record = {
        "ts": datetime.now(BJT).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "server_time": server_time,
        "lng": LNG,
        "lat": LAT,
        # ---- 输入特征（回归自变量）----
        "temperature": temp,                              # °C
        "humidity": humidity,                             # 相对湿度 0-1
        "wind_speed": wind_speed,                         # m/s
        "wind_direction": wind.get("direction", 0),       # °
        "cloudrate": rt.get("cloudrate"),                 # 云量 0-1
        "dswrf": rt.get("dswrf"),                         # 向下短波辐射 W/m²
        "pres": rt.get("pres"),                           # 气压 Pa
        "visibility": rt.get("visibility"),               # 能见度 km
        "skycon": rt.get("skycon"),                       # 天气现象
        "aqi": rt.get("aqi"),                             # AQI
        "precip_local_intensity": ((rt.get("precipitation") or {}).get("local") or {}).get("intensity"),  # 本地降雨 mm/h
        # ---- 目标值 y ----
        "apparent_temperature": rt.get("apparent_temperature", temp),  # 官方体感温度 °C
        # ---- 基线：脚本当前启发式估算 ----
        "est_apparent_temperature": apparent_temperature(temp, humidity, wind_speed),
    }
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    with open(APPARENT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    data = fetch_weather()
    if not data or data.get("status") != "ok":
        print("彩云 | refresh=true")
        print("---")
        print("获取天气失败 | refresh=true")
        print("刷新 | refresh=true terminal=false bash=/usr/bin/python3 param1=-c param2='import time; time.sleep(1)'")
        return

    result = data.get("result", {})
    rt = result.get("realtime", {})

    # 体感温度数据采集（写日志，不影响展示）
    log_apparent_data(data)

    daily = result.get("daily", {})
    forecast_keypoint = result.get("forecast_keypoint", "")

    # 数据更新时间
    server_time = data.get("server_time", 0)
    update_dt = datetime.fromtimestamp(server_time)
    update_str = update_dt.strftime("%H:%M")

    temp = rt.get("temperature", 0)
    skycon_raw = rt.get("skycon", "UNKNOWN")
    skycon = SKYCON_MAP.get(skycon_raw, skycon_raw)
    aqi = int(rt.get("aqi", 0) or 0)
    aqi_text = aqi_level(aqi)
    humidity = int((rt.get("humidity", 0) or 0) * 100)
    wind = rt.get("wind", {})
    wind_speed = wind.get("speed", 0)
    wind_dir = wind_direction(wind.get("direction", 0))
    apparent_temp = rt.get("apparent_temperature", temp)
    uv = rt.get("ultraviolet", {})
    comfort = rt.get("comfort", {})

    # 分钟级预报
    minutely = result.get("minutely", {})

    # 逐小时预报
    hourly = result.get("hourly", {})
    hourly_temp = hourly.get("temperature", [])
    hourly_skycon = hourly.get("skycon", [])
    hourly_precip = hourly.get("precipitation", [])
    hourly_wind = hourly.get("wind", [])
    hourly_aqi = hourly.get("aqi", [])
    hourly_humidity = hourly.get("humidity", [])

    # 未来3天预报
    daily_temp = daily.get("temperature", [])
    daily_skycon = daily.get("skycon", [])
    daily_aqi = daily.get("aqi", [])
    daily_wind = daily.get("wind", [])

    # 菜单栏标题 (简洁)
    # title_icon = skycon.split()[0] if " " in skycon else "🌡️"
    # title_icon = skycon.split()[1] if " " in skycon else ""
    title_icon = skycon.replace(' ', '')
    # print(f"{title_icon}  {temp:.1f}°C | font='Sarasa Mono SC' refresh=true size=13")
    print(f"{title_icon} {temp:.1f} | font='Sarasa Mono SC' refresh=true size=13")
    print("---")

    # 数据更新时间
    print(f"更新于 {update_str} | font='Sarasa Mono SC' size=13 refresh=true")
    print("---")

    # 预报摘要
    if forecast_keypoint:
        cleaned_forecast_keypoint = re.sub(r'呢|最近的|吧|~|哦|您|还是|把', '', forecast_keypoint)
        forecast_keypoint_list = cleaned_forecast_keypoint.split('，')
        for lines in forecast_keypoint_list:
            print(f"{lines} | font='Sarasa Mono SC' size=13 refresh=true")
        print("---")

    # 实时天气
    print(f"🌡️ 温度 {temp:.1f}°C  体感 {apparent_temp:.1f}°C | font='Sarasa Mono SC' size=13 refresh=true")
    # print(f"🌤️ 天气状况: {skycon} | font='Sarasa Mono SC' size=13")
    print(f"相对湿度: {humidity}% | font='Sarasa Mono SC' size=13 refresh=true")
    # print(f"💨 风向风速: {wind_dir}风 {wind_speed:.1f}m/s ({wind_desc(wind_speed)}) | font='Sarasa Mono SC' size=13")
    # print(f"👁️ 能见度: {rt.get('visibility', 0):.1f}km | font='Sarasa Mono SC' size=13")
    # print(f"🔽 气压: {rt.get('pres', 0) / 100:.0f}hPa | font='Sarasa Mono SC' size=13")
    print("---")



    if minutely.get("status") == "ok":
        m_precip_2h = minutely.get("precipitation_2h", [])
        chart_b64 = render_rain_chart(m_precip_2h)
        if chart_b64:
            # print(f"📊 未来2h降雨趋势 | font='Sarasa Mono SC' size=13 refresh=true")
            print(f" | image={chart_b64} refresh=true")

    print("---")

    # 空气质量
    # pm25 = rt.get("pm25", 0)
    # pm10 = rt.get("pm10", 0)
    # o3 = rt.get("o3", 0)
    # no2 = rt.get("no2", 0)
    # so2 = rt.get("so2", 0)
    # co = rt.get("co", 0)
    # print(f"🫁 AQI: {aqi} {aqi_text} | font='Sarasa Mono SC' size=13")
    # print(f"   PM2.5: {pm25}  PM10: {pm10}  O₃: {o3} | font=Menlo size=13 color=#888888 refresh=true")
    # print(f"   NO₂: {no2}  SO₂: {so2}  CO: {co} | font=Menlo size=13 color=#888888 refresh=true")
    # print("---")


    # 紫外线 & 舒适度
    # uv_index = uv.get("index", 0)
    # uv_desc = uv.get("desc", "")
    # comfort_desc = comfort.get("desc", "")
    # if uv_desc:
    #     print(f"☀️ 紫外线: {uv_desc} (指数{uv_index}) | font='Sarasa Mono SC' size=13")
    # if comfort_desc:
    #     print(f"😌 舒适度: {comfort_desc} | font='Sarasa Mono SC' size=13")
    # if uv_desc or comfort_desc:
    #     print("---")

    # 未来预报
    weekdays = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
    today = datetime.now()

    # 逐小时预报 (今天起未来12小时)
    if hourly_temp:
        now = datetime.now()
        # 找到当前小时或下一个小时的索引
        start_idx = 0
        for idx, h in enumerate(hourly_temp):
            dt_str = h.get("datetime", "")
            try:
                h_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                if h_dt.date() == now.date() and h_dt.hour == now.hour:
                    start_idx = idx
                    break
                elif h_dt > now and start_idx == 0:
                    start_idx = idx
            except Exception:
                continue

        hourly_count = len(hourly_temp)
        direct_hours = 12
        end_idx = min(start_idx + direct_hours, hourly_count)
        for i in range(start_idx, end_idx):
            # 仅当前 10 小时且无雨时显示体感温度
            show_apparent = (i - start_idx) < 24
            line = format_hourly_line(i, hourly_temp, hourly_skycon, hourly_precip, hourly_wind, hourly_aqi, now,
                                      hourly_humidity, show_apparent)
            print(f"{line} | font='Sarasa Mono SC' size=13 refresh=true")

        # 12 小时以上的更长远期预报，放入可折叠子菜单
        if end_idx < hourly_count:
            print("逐小时预报 | font='Sarasa Mono SC' size=13 refresh=true")
            for i in range(end_idx, hourly_count):
                line = format_hourly_line(i, hourly_temp, hourly_skycon, hourly_precip, hourly_wind, hourly_aqi, now,
                                          hourly_humidity, show_apparent)
                print(f"-- {line} | font='Sarasa Mono SC' size=13 refresh=true")
        print("---")

    # 未来天级预报
    today = datetime.now()
    daily_count = len(daily_temp)
    direct_days = 7
    for i in range(min(direct_days, daily_count)):
        line = format_daily_line(i, daily_temp, daily_skycon, daily_aqi, daily_wind, today, weekdays)
        print(f"{line} | font='Sarasa Mono SC' size=13 refresh=true")

    # 更多天级预报放入可折叠子菜单
    if daily_count > direct_days:
        print("天级预报 | font='Sarasa Mono SC' size=13 refresh=true")
        for i in range(direct_days, daily_count):
            line = format_daily_line(i, daily_temp, daily_skycon, daily_aqi, daily_wind, today, weekdays)
            print(f"-- {line} | font='Sarasa Mono SC' size=13 refresh=true")

    print("---")
    print("彩云天气 | href=https://www.caiyunapp.com/h5/ refresh=true")
    # print("刷新 | refresh=true terminal=false")


if __name__ == "__main__":
    main()
