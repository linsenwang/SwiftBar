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
刷新频率: 2分钟
"""

import json
import urllib.request
import urllib.error
import random
from datetime import datetime, timedelta

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
LNG, LAT = "118.0987", "24.4365"
API_URL = f"https://api.caiyunapp.com/v2/{TOKEN}/{LNG},{LAT}/weather.jsonp"

# 天气现象映射
SKYCON_MAP = {
    "CLEAR_DAY": "☀️ 晴",
    "CLEAR_NIGHT": "🌙 晴",
    "PARTLY_CLOUDY_DAY": "⛅ 多云",
    "PARTLY_CLOUDY_NIGHT": "🌤️ 多云",
    "CLOUDY": "☁️ 阴",
    "LIGHT_RAIN": "🌧️ 小雨",
    "MODERATE_RAIN": "🌧️ 中雨",
    "HEAVY_RAIN": "⛈️ 大雨",
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
    precip = rt.get("precipitation", {})
    nearest_rain = precip.get("nearest", {})
    local_rain = precip.get("local", {})

    # 逐小时预报
    hourly = result.get("hourly", {})
    hourly_temp = hourly.get("temperature", [])
    hourly_skycon = hourly.get("skycon", [])
    hourly_precip = hourly.get("precipitation", [])
    hourly_wind = hourly.get("wind", [])
    hourly_aqi = hourly.get("aqi", [])

    # 未来3天预报
    daily_temp = daily.get("temperature", [])
    daily_skycon = daily.get("skycon", [])
    daily_aqi = daily.get("aqi", [])
    daily_wind = daily.get("wind", [])

    # 菜单栏标题 (简洁)
    # title_icon = skycon.split()[0] if " " in skycon else "🌡️"
    # title_icon = skycon.split()[1] if " " in skycon else ""
    title_icon = skycon.replace(' ', '')
    print(f"{title_icon}  {temp:.1f}°C | refresh=true size=13")
    print("---")

    # 数据更新时间
    print(f"更新于 {update_str} | font=PingFangSC size=13 refresh=true")
    print("---")

    # 预报摘要
    if forecast_keypoint:
        print(f"{forecast_keypoint.replace('呢', '').replace('最近的', '')} | font=PingFangSC size=13 refresh=true")
        print("---")

    # 实时天气
    print(f"🌡️ 温度 {temp:.1f}°C  体感 {apparent_temp:.1f}°C | font=PingFangSC size=13 refresh=true")
    # print(f"🌤️ 天气状况: {skycon} | font=PingFangSC size=13")
    print(f"相对湿度: {humidity}% | font=PingFangSC size=13 refresh=true")
    # print(f"💨 风向风速: {wind_dir}风 {wind_speed:.1f}m/s ({wind_desc(wind_speed)}) | font=PingFangSC size=13")
    # print(f"👁️ 能见度: {rt.get('visibility', 0):.1f}km | font=PingFangSC size=13")
    # print(f"🔽 气压: {rt.get('pres', 0) / 100:.0f}hPa | font=PingFangSC size=13")
    print("---")

    # 降雨信息
    if local_rain.get("status") == "ok":
        intensity = local_rain.get("intensity", 0)
        if intensity > 0:
            print(f"🌧️ 当前降雨: {intensity:.2f}mm/h | font=PingFangSC size=13 refresh=true")
        elif nearest_rain.get("status") == "ok":
            dist = nearest_rain.get("distance", 0)
            # if dist > 0:
            #     print(f"☁️ 最近降雨: {dist:.0f}km 外 | font=PingFangSC size=13 refresh=true")
    print("---")

    # 空气质量
    # pm25 = rt.get("pm25", 0)
    # pm10 = rt.get("pm10", 0)
    # o3 = rt.get("o3", 0)
    # no2 = rt.get("no2", 0)
    # so2 = rt.get("so2", 0)
    # co = rt.get("co", 0)
    # print(f"🫁 AQI: {aqi} {aqi_text} | font=PingFangSC size=13")
    # print(f"   PM2.5: {pm25}  PM10: {pm10}  O₃: {o3} | font=Menlo size=13 color=#888888 refresh=true")
    # print(f"   NO₂: {no2}  SO₂: {so2}  CO: {co} | font=Menlo size=13 color=#888888 refresh=true")
    # print("---")


    # 紫外线 & 舒适度
    # uv_index = uv.get("index", 0)
    # uv_desc = uv.get("desc", "")
    # comfort_desc = comfort.get("desc", "")
    # if uv_desc:
    #     print(f"☀️ 紫外线: {uv_desc} (指数{uv_index}) | font=PingFangSC size=13")
    # if comfort_desc:
    #     print(f"😌 舒适度: {comfort_desc} | font=PingFangSC size=13")
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
                if h_dt.hour == now.hour:
                    start_idx = idx
                    break
                elif h_dt > now and start_idx == 0:
                    start_idx = idx
            except Exception:
                continue

        # print("⏰ 逐小时预报 | font=PingFangSC size=13")
        for i in range(start_idx, min(start_idx + 12, len(hourly_temp))):
            h_temp = hourly_temp[i]
            h_sky = hourly_skycon[i] if i < len(hourly_skycon) else {}
            h_precip = hourly_precip[i] if i < len(hourly_precip) else {}
            h_wind = hourly_wind[i] if i < len(hourly_wind) else {}
            h_aqi = hourly_aqi[i] if i < len(hourly_aqi) else {}

            dt_str = h_temp.get("datetime", "")
            try:
                h_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                time_label = h_dt.strftime("%H:%M")
                if h_dt.hour == now.hour:
                    time_label = "现在"
            except Exception:
                time_label = "--:--"

            temp_val = h_temp.get("value", 0)
            sky_val = SKYCON_MAP.get(h_sky.get("value", ""), h_sky.get("value", ""))
            sky_icon = sky_val.split()[0] if " " in sky_val else "🌡️"
            sky_text = sky_val.split()[-1] if " " in sky_val else sky_val
            precip_val = h_precip.get("value", 0)
            precip_str = f"💧{precip_val:.1f}mm" if precip_val > 0.05 else ""
            w_spd = h_wind.get("speed", 0)
            w_dir = wind_direction(h_wind.get("direction", 0))
            aqi_val = int(h_aqi.get("value", 0) or 0)
            aqi_icon = "🟢" if aqi_val <= 50 else ("🟡" if aqi_val <= 100 else "🟠")

            parts = [f"{sky_icon} {time_label} {temp_val:.0f}° {sky_text}"]
            if precip_str:
                parts.append(precip_str)
            # parts.append(f"💨{w_dir}{w_spd:.0f}m/s")
            # parts.append(f"AQI{aqi_icon}{aqi_val}")
            line = " ".join(parts)
            print(f"{line} | font=PingFangSC size=13 refresh=true")
        print("---")

    # 未来天级预报
    # print("📅 未来预报 | font=PingFangSC size=13")
    today = datetime.now()
    for i in range(min(5, len(daily_temp))):
        dt = today + timedelta(days=i)
        wd = weekdays[dt.weekday()]
        date_str = dt.strftime("%m-%d")
        label = "今天" if i == 0 else ("明天" if i == 1 else f"{wd}")

        t = daily_temp[i]
        s = daily_skycon[i] if i < len(daily_skycon) else {}
        a = daily_aqi[i] if i < len(daily_aqi) else {}
        w = daily_wind[i] if i < len(daily_wind) else {}

        t_max = t.get("max", 0)
        t_min = t.get("min", 0)
        sky = SKYCON_MAP.get(s.get("value", ""), s.get("value", ""))
        sky_icon = sky.split()[0] if " " in sky else "🌡️"
        aqi_val = int(a.get("avg", 0) or 0)
        aqi_lbl = aqi_level(aqi_val).split()[1]

        w_avg = w.get("avg", {})
        w_spd = w_avg.get("speed", 0)
        w_dir_val = w_avg.get("direction", 0)
        w_dir_str = wind_direction(w_dir_val)

        # line = f"{sky_icon} {label}({date_str}) {t_min:.0f}°~{t_max:.0f}° {sky.split()[-1] if ' ' in sky else sky} 风{w_dir_str}{w_spd:.0f}m/s AQI{aqi_val}{aqi_lbl}"
        line = f"{sky_icon} {label} {date_str} {t_min:.0f}°~{t_max:.0f}° {sky.split()[-1] if ' ' in sky else sky}"
        print(f"{line} | font=PingFangSC size=13 refresh=true")

    print("---")
    print("彩云天气 | href=https://www.caiyunapp.com/h5/ refresh=true")
    # print("刷新 | refresh=true terminal=false")


if __name__ == "__main__":
    main()
