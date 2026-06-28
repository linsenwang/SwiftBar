# 彩云天气 H5 API 文档

> **数据来源**: 基于 `2026-06-10 20:00` 对 `https://api.caiyunapp.com/v2/{token}/{lng},{lat}/weather.jsonp` 的真实请求响应编写。
> 
> **Token**: `Y2FpeXVuIGFwaSB3ZWI` (H5 页面硬编码)

---

## 1. 请求说明

```
GET https://api.caiyunapp.com/v2/{TOKEN}/{LNG},{LAT}/weather.jsonp?hourlysteps=120&random={random}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `TOKEN` | string | 是 | API 认证令牌 |
| `LNG` | string | 是 | 经度 |
| `LAT` | string | 是 | 纬度 |
| `hourlysteps` | int | 否 | 逐小时预报步数，默认 `48`，实测可取到 `120` |
| `random` | float | 否 | 随机数，用于绕过缓存 |

**请求头（必须）**:
```
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ...
Referer: https://www.caiyunapp.com/h5/
```

---

## 2. 响应顶层结构

```json
{
  "status": "ok",
  "api_version": "v2.2",
  "api_status": "deprecated",
  "lang": "zh_CN",
  "unit": "metric",
  "tzshift": 28800,
  "timezone": "Asia/Shanghai",
  "server_time": 1781095176,
  "location": [24.4365, 118.0987],
  "result": { ... }
}
```

| 字段 | 类型 | 代码已用 | 说明 |
|------|------|:--------:|------|
| `status` | string | ✅ | 请求状态，`ok` 表示成功 |
| `api_version` | string | ❌ | API 版本，本次为 `v2.2` |
| `api_status` | string | ❌ | API 状态，本次为 `deprecated` |
| `lang` | string | ❌ | 语言 |
| `unit` | string | ❌ | 单位制，`metric` |
| `tzshift` | int | ❌ | 时区偏移秒数，`28800` = UTC+8 |
| `timezone` | string | ❌ | 时区名称 |
| `server_time` | int | ✅ | 服务器 Unix 时间戳（秒） |
| `location` | [float, float] | ❌ | 请求坐标 `[lat, lng]`（注意顺序是 lat 在前） |

---

## 3. `result` 主体

### 3.1 实时天气 (`result.realtime`)

```json
{
  "status": "ok",
  "temperature": 24.41,
  "humidity": 0.78,
  "cloudrate": 0.3,
  "skycon": "PARTLY_CLOUDY_NIGHT",
  "visibility": 12.03,
  "dswrf": 0.0,
  "wind": { "speed": 16.7, "direction": 70.73 },
  "pres": 100622.61,
  "apparent_temperature": 24.4,
  "precipitation": {
    "local": { "status": "ok", "datasource": "radar", "intensity": 0.0 },
    "nearest": { "status": "ok", "distance": 33.96, "intensity": 0.1875 }
  },
  "aqi": 58,
  "pm25": 28,
  "pm10": 61,
  "o3": 97,
  "so2": 6,
  "no2": 17,
  "co": 0.5,
  "ultraviolet": { "index": 0, "desc": "无" },
  "comfort": { "index": 4, "desc": "温暖" }
}
```

| 字段 | 类型 | 单位 | 代码已用 | 说明 |
|------|------|------|:--------:|------|
| `status` | string | — | ✅ | 数据状态 |
| `temperature` | float | °C | ✅ | 温度 |
| `humidity` | float | 0-1 | ✅ | 相对湿度 |
| `cloudrate` | float | 0-1 | ❌ | **云量，代码未使用** |
| `skycon` | string | — | ✅ | 天气现象代码 |
| `visibility` | float | km | ⚠️ | 能见度，代码已读取但被注释掉 |
| `dswrf` | float | W/m² | ❌ | **向下短波辐射通量（太阳辐射），代码未使用** |
| `wind.speed` | float | m/s | ✅ | 风速 |
| `wind.direction` | float | ° | ✅ | 风向角度 |
| `pres` | float | Pa | ⚠️ | 气压，代码已读取但被注释掉（需 ÷100 转 hPa） |
| `apparent_temperature` | float | °C | ✅ | 体感温度 |
| `precipitation.local.status` | string | — | ✅ | 本地降雨数据状态 |
| `precipitation.local.datasource` | string | — | ❌ | **降雨数据来源（如 `radar`），代码未使用** |
| `precipitation.local.intensity` | float | mm/h | ✅ | 本地降雨强度 |
| `precipitation.nearest.status` | string | — | ✅ | 最近降雨数据状态 |
| `precipitation.nearest.distance` | float | km | ✅ | 最近降雨区距离 |
| `precipitation.nearest.intensity` | float | mm/h | ❌ | **最近降雨区强度，代码未使用** |
| `aqi` | int | — | ✅ | AQI 指数 |
| `pm25` | int | μg/m³ | ⚠️ | 已读取但被注释掉 |
| `pm10` | int | μg/m³ | ⚠️ | 已读取但被注释掉 |
| `o3` | int | μg/m³ | ⚠️ | 已读取但被注释掉 |
| `so2` | int | μg/m³ | ⚠️ | 已读取但被注释掉 |
| `no2` | int | μg/m³ | ⚠️ | 已读取但被注释掉 |
| `co` | float | mg/m³ | ⚠️ | 已读取但被注释掉 |
| `ultraviolet.index` | int | — | ⚠️ | 紫外线指数，已读取但被注释掉 |
| `ultraviolet.desc` | string | — | ⚠️ | 紫外线描述，已读取但被注释掉 |
| `comfort.index` | int | — | ⚠️ | 舒适度指数，已读取但被注释掉 |
| `comfort.desc` | string | — | ⚠️ | 舒适度描述，已读取但被注释掉 |

---

### 3.2 分钟级预报 (`result.minutely`)

```json
{
  "status": "ok",
  "datasource": "radar",
  "precipitation_2h": [0.0, 0.0, ...],
  "precipitation": [0.0, 0.0, ...],
  "probability": [0.0, 0.0, 0.0, 0.0],
  "description": "最近的降雨带在南边34公里外呢"
}
```

| 字段 | 类型 | 长度 | 代码已用 | 说明 |
|------|------|------|:--------:|------|
| `status` | string | — | ✅ | 数据状态 |
| `datasource` | string | — | ❌ | **数据来源，代码未使用** |
| `precipitation_2h` | [float] | 120 | ✅ | 未来 120 分钟每分钟降雨强度（mm/h） |
| `precipitation` | [float] | 60 | ❌ | **另一组分钟级降雨数据（60个），代码未使用** |
| `probability` | [float] | 4 | ❌ | **降雨概率（仅4个值），代码未使用** |
| `description` | string | — | ⚠️ | 分钟级描述，代码读取但被注释掉 |

---

### 3.3 逐小时预报 (`result.hourly`)

```json
{
  "status": "ok",
  "description": "未来24小时多云",
  "precipitation": [{"datetime": "...", "value": 0.0}, ...],
  "temperature": [{"datetime": "...", "value": 24.41}, ...],
  "skycon": [{"datetime": "...", "value": "PARTLY_CLOUDY_NIGHT"}, ...],
  "wind": [{"datetime": "...", "speed": 16.7, "direction": 70.73}, ...],
  "aqi": [{"datetime": "...", "value": 58}, ...],
  "cloudrate": [{"datetime": "...", "value": 0.3}, ...],
  "dswrf": [{"datetime": "...", "value": 0.0}, ...],
  "humidity": [{"datetime": "...", "value": 0.78}, ...],
  "pm25": [{"datetime": "...", "value": 28}, ...],
  "pres": [{"datetime": "...", "value": 100622.61}, ...],
  "visibility": [{"datetime": "...", "value": 12.03}, ...]
}
```

| 字段 | 类型 | 代码已用 | 说明 |
|------|------|:--------:|------|
| `status` | string | ✅ | 数据状态 |
| `description` | string | ❌ | **逐小时整体描述（如"未来24小时多云"），代码未使用** |
| `precipitation[].datetime` / `value` | string / float | ✅ | 逐小时降雨强度 |
| `temperature[].datetime` / `value` | string / float | ✅ | 逐小时温度 |
| `skycon[].datetime` / `value` | string / string | ✅ | 逐小时天气现象 |
| `wind[].datetime` / `speed` / `direction` | string / float / float | ✅ | 逐小时风速风向 |
| `aqi[].datetime` / `value` | string / int | ✅ | 逐小时 AQI |
| `cloudrate[].datetime` / `value` | string / float | ❌ | **逐小时云量，代码未使用** |
| `dswrf[].datetime` / `value` | string / float | ❌ | **逐小时太阳辐射，代码未使用** |
| `humidity[].datetime` / `value` | string / float | ❌ | **逐小时湿度，代码未使用** |
| `pm25[].datetime` / `value` | string / int | ❌ | **逐小时 PM2.5，代码未使用** |
| `pres[].datetime` / `value` | string / float | ❌ | **逐小时气压，代码未使用** |
| `visibility[].datetime` / `value` | string / float | ❌ | **逐小时能见度，代码未使用** |

---

### 3.4 逐日预报 (`result.daily`)

```json
{
  "status": "ok",
  "temperature": [{"date": "2026-06-10", "max": 25.0, "min": 21.8, "avg": 23.51}, ...],
  "skycon": [{"date": "...", "value": "PARTLY_CLOUDY_NIGHT"}, ...],
  "skycon_08h_20h": [{"date": "...", "value": "CLOUDY"}, ...],
  "skycon_20h_32h": [{"date": "...", "value": "PARTLY_CLOUDY_NIGHT"}, ...],
  "aqi": [{"date": "...", "max": 58, "min": 25, "avg": 41}, ...],
  "pm25": [{"date": "...", "max": 28, "min": 3, "avg": 22}, ...],
  "wind": [
    {
      "date": "2026-06-10",
      "max": {"speed": 20.03, "direction": 81.52},
      "min": {"speed": 1.14, "direction": 312.12},
      "avg": {"speed": 9.73, "direction": 76.99}
    }
  ],
  "astro": [{"date": "...", "sunrise": {"time": "05:18"}, "sunset": {"time": "18:55"}}],
  "cloudrate": [{"date": "...", "max": 1.0, "min": 0.3, "avg": 0.59}, ...],
  "dswrf": [{"date": "...", "max": 696.8, "min": 0.0, "avg": 0.0}, ...],
  "humidity": [{"date": "...", "max": 0.93, "min": 0.71, "avg": 0.74}, ...],
  "precipitation": [{"date": "...", "max": 1.2377, "min": 0.0, "avg": 0.0}, ...],
  "pres": [{"date": "...", "max": 100713.03, "min": 100130.08, "avg": 100676.14}, ...],
  "visibility": [{"date": "...", "max": 24.14, "min": 9.93, "avg": 12.23}, ...],
  "ultraviolet": [{"datetime": "...", "index": "2", "desc": "弱"}, ...],
  "carWashing": [{"datetime": "...", "index": "1", "desc": "适宜"}, ...],
  "coldRisk": [{"datetime": "...", "index": "3", "desc": "易发"}, ...],
  "comfort": [{"datetime": "...", "index": "4", "desc": "温暖"}, ...],
  "dressing": [{"datetime": "...", "index": "3", "desc": "热"}, ...]
}
```

| 字段 | 类型 | 代码已用 | 说明 |
|------|------|:--------:|------|
| `status` | string | ✅ | 数据状态 |
| `temperature[].date` / `max` / `min` / `avg` | string / float | ✅ | 每日温度范围 |
| `skycon[].date` / `value` | string / string | ✅ | 全天天气现象 |
| `skycon_08h_20h[].date` / `value` | string / string | ❌ | **白天（08-20时）天气现象，代码未使用** |
| `skycon_20h_32h[].date` / `value` | string / string | ❌ | **夜间（20-32时）天气现象，代码未使用** |
| `aqi[].date` / `max` / `min` / `avg` | string / int | ✅ | 每日 AQI 范围 |
| `pm25[].date` / `max` / `min` / `avg` | string / int | ❌ | **每日 PM2.5 范围，代码未使用** |
| `wind[].date` / `avg` | string / object | ✅ | 每日平均风速风向 |
| `wind[].max` / `wind[].min` | object | ❌ | **每日最大/最小风速风向，代码未使用** |
| `astro[].date` / `sunrise.time` / `sunset.time` | string / string | ❌ | **日出日落时间，代码未使用** |
| `cloudrate[].date` / `max` / `min` / `avg` | string / float | ❌ | **每日云量范围，代码未使用** |
| `dswrf[].date` / `max` / `min` / `avg` | string / float | ❌ | **每日太阳辐射范围，代码未使用** |
| `humidity[].date` / `max` / `min` / `avg` | string / float | ❌ | **每日湿度范围，代码未使用** |
| `precipitation[].date` / `max` / `min` / `avg` | string / float | ❌ | **每日降雨范围，代码未使用** |
| `pres[].date` / `max` / `min` / `avg` | string / float | ❌ | **每日气压范围，代码未使用** |
| `visibility[].date` / `max` / `min` / `avg` | string / float | ❌ | **每日能见度范围，代码未使用** |
| `ultraviolet[].datetime` / `index` / `desc` | string / string / string | ❌ | **每日紫外线指数，代码未使用** |
| `carWashing[].datetime` / `index` / `desc` | string / string / string | ❌ | **洗车指数，代码未使用** |
| `coldRisk[].datetime` / `index` / `desc` | string / string / string | ❌ | **感冒风险指数，代码未使用** |
| `comfort[].datetime` / `index` / `desc` | string / string / string | ❌ | **舒适度指数，代码未使用** |
| `dressing[].datetime` / `index` / `desc` | string / string / string | ❌ | **穿衣指数，代码未使用** |

---

### 3.5 预报摘要 (`result.forecast_keypoint`)

| 字段 | 类型 | 代码已用 | 说明 |
|------|------|:--------:|------|
| `forecast_keypoint` | string | ✅ | 一句话天气摘要，如 `"最近的降雨带在南边34公里外呢"` |

### 3.6 其他顶层字段

| 字段 | 类型 | 代码已用 | 说明 |
|------|------|:--------:|------|
| `primary` | int | ❌ | **含义不明，本次值为 `0`，代码未使用** |

> ⚠️ **注意**: 本次真实请求未返回 `alert`（天气预警）字段，因此无法确认该 token + 坐标下此字段是否存在。代码中也完全没有处理预警逻辑。

---

## 4. 遗漏信息汇总

### 4.1 已获取但被注释掉的字段（数据拿到了，UI 没展示）

| 字段 | 所在模块 | 展示建议 |
|------|----------|----------|
| `pres` | realtime | `1006 hPa` |
| `visibility` | realtime | `12.0 km` |
| `pm25`, `pm10`, `o3`, `so2`, `no2`, `co` | realtime | 展开详细空气质量面板 |
| `ultraviolet.index` / `desc` | realtime | `紫外线: 无` |
| `comfort.index` / `desc` | realtime | `舒适度: 温暖` |
| `minutely.description` | minutely | `⏱️ 最近的降雨带在南边34公里外呢` |

### 4.2 真实响应中有、但代码完全未读取的字段

#### realtime
- `cloudrate` — 云量 30%，可补充天气描述
- `dswrf` — 太阳辐射 0 W/m²，夜间为 0，白天有值
- `precipitation.local.datasource` — 数据来源 `radar`
- `precipitation.nearest.intensity` — 最近降雨区强度 `0.1875 mm/h`

#### minutely
- `datasource` — `radar`
- `precipitation` — 60 分钟降雨数组（与 `precipitation_2h` 的关系不明）
- `probability` — 仅 4 个值的降雨概率数组

#### hourly
- `description` — 整体描述如 `"未来24小时多云"`
- `cloudrate`, `dswrf`, `humidity`, `pm25`, `pres`, `visibility` — 完整的小时级环境数据

#### daily（大量生活指数和范围数据）
- `skycon_08h_20h` / `skycon_20h_32h` — 白天/夜间天气细分
- `wind.max` / `wind.min` — 日最大/最小风速
- `astro` — **日出日落时间**（最有展示价值）
- `pm25`, `cloudrate`, `dswrf`, `humidity`, `precipitation`, `pres`, `visibility` — 日范围统计
- `ultraviolet`, `carWashing`, `coldRisk`, `comfort`, `dressing` — **生活指数**

---

## 5. 建议优先补充的展示项

1. **日出日落** (`daily.astro[].sunrise.time` / `sunset.time`) — 实用价值高，代码简单
2. **降雨概率** (`minutely.probability[]`) — 比纯强度更有决策参考价值（虽然只有 4 个值）
3. **逐小时整体描述** (`hourly.description`) — 可放在逐小时预报标题处
4. **云量** (`realtime.cloudrate`) — 补充 `"多云"` 之类的描述更精确
5. **生活指数** (`daily.carWashing`, `dressing`, `coldRisk`, `ultraviolet`) — 可作为二级菜单展示
