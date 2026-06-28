# SwiftBar 语法速查与复用手册

> 本仓库内所有 SwiftBar 插件共用的一套语法统计与模板，方便后续写新插件时直接复制。

## 1. 项目中的 SwiftBar 插件

| 文件 | 刷新频率 | 功能 |
|------|----------|------|
| `caiyun_weather.10m.py` | 10 分钟 | 彩云天气菜单栏 + 下拉详情 |
| `kimi_beta_mode.2m.py` | 2 分钟 | Kimi Code Beta 模式切换 |
| `kimi_usage.2m.py` | 2 分钟 | Kimi Code 用量监控 |
| `notion_todo.2m.py` | 2 分钟 | Notion 待办任务管理 |
| `.archive/capswriter.5s.py` | 5 秒 | CapsWriter 状态监控（已归档） |

> 非插件脚本：`notion_todo_auth.py`、`sync_ms_todo_to_notion.py` 只输出普通文本，不生成 SwiftBar 菜单。

---

## 2. 文件名约定

SwiftBar 通过文件名中的间隔标识自动决定刷新周期：

```text
<name>.<interval>.<ext>
```

| 本项目用到的后缀 | 含义 | 文件数 |
|----------------|------|--------|
| `.2m.` | 每 2 分钟刷新 | 3 |
| `.10m.` | 每 10 分钟刷新 | 1 |
| `.5s.` | 每 5 秒刷新 | 1 |

可用单位：`s`（秒）、`m`（分）、`h`（时）、`d`（天）。

---

## 3. 元数据指令（Metadata）

每个插件顶部都会用 **注释形式** 的 XML 标签隐藏 SwiftBar 默认菜单项，让菜单更干净。

```python
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>
```

| 指令 | 出现次数 | 作用 |
|------|----------|------|
| `hideAbout` | 5 | 隐藏 "About" 菜单项 |
| `hideRunInTerminal` | 5 | 隐藏 "Run in Terminal" 菜单项 |
| `hideLastUpdated` | 5 | 隐藏 "Last Updated" 菜单项 |
| `hideDisablePlugin` | 5 | 隐藏 "Disable Plugin" 菜单项 |
| `hideSwiftBar` | 5 | 隐藏 SwiftBar 自身相关菜单项 |

**总计：25 条元数据指令。**

常用但未在本项目使用的指令（可扩展）：

```python
# <swiftbar.refreshOnOpen>true</swiftbar.refreshOnOpen>
# <swiftbar.hideDropdown>false</swiftbar.hideDropdown>
# <swiftbar.runInBash>true</swiftbar.runInBash>
# <swiftbar.environment>VAR1=value1,VAR2=value2</swiftbar.environment>
# <swiftbar.droptypes>public.text</swiftbar.droptypes>
```

---

## 4. 输出结构

### 4.1 菜单栏标题

脚本输出的**第一行**会显示在菜单栏上，其余行进入下拉菜单。

```python
print("🌡️  26.5°C | refresh=true size=13")
print("Kβ? | href=https://www.kimi.com/code/beta")
print("⚪️ CW | color=#999999")
```

### 4.2 分隔线

用 `---` 作为单独一行输出，会在下拉菜单里产生一条分隔线，同时标志着“标题行结束、下拉菜单开始”。

```python
print("菜单栏标题 | refresh=true")
print("---")           # 标题与下拉菜单的分隔
print("第一项")
print("---")           # 组内分隔线
print("第二项")
```

**本项目使用统计：** `---` 共出现 **29 次**。

### 4.3 子菜单

行首加 `--` 表示该项属于上一行的子菜单。

```python
print("逐小时预报 | font=PingFangSC size=13 refresh=true")
print(f"-- {line} | font=PingFangSC size=13 refresh=true")

print("☐ 任务标题 | bash=... terminal=false refresh=true")
print("-- ✅ 完成 | bash=... terminal=false refresh=true")
print("-- 🗑 删除 | bash=... terminal=false refresh=true")
```

**本项目使用统计：** `--` 子菜单项共 **4 次**。

---

## 5. 行内参数（`| key=value`）

SwiftBar 用 `|` 把“显示文本”和“参数”分开。多个参数用空格分隔。

```
显示文本 | key1=value1 key2=value2
```

**本项目统计：共 48 行带参数，96 次参数使用。**

### 5.1 参数使用频率表

| 参数 | 次数 | 说明 | 示例 |
|------|------|------|------|
| `refresh` | 29 | 点击后是否刷新插件 | `refresh=true` |
| `size` | 15 | 字体大小 | `size=13` |
| `font` | 12 | 字体名称 | `font=PingFangSC`、`font=Menlo` |
| `color` | 8 | 文本颜色 | `color=red`、`color=#FF0000` |
| `href` | 7 | 点击用默认浏览器打开 URL | `href=https://www.kimi.com/code/beta` |
| `terminal` | 7 | `bash` 动作是否打开终端 | `terminal=false` |
| `bash` | 7 | 点击执行的命令 | `bash={SCRIPT_PATH}`、`bash=open` |
| `param1` | 7 | 传给 `bash` 的第 1 个参数 | `param1=start_client` |
| `param2` | 3 | 传给 `bash` 的第 2 个参数 | `param2=--toggle` |
| `image` | 1 | 显示 Base64 PNG 图片 | `image={chart_b64}` |

### 5.2 常用参数详解

#### `refresh`

```python
print("彩云 | refresh=true")
```

- 几乎所有可点击项都加 `refresh=true`，让菜单在操作后自动刷新。
- 标题行也建议加，保证定时刷新正常。

#### `size` / `font`

```python
print(f"{line} | font=PingFangSC size=13 refresh=true")
print(f"{format_reset_time(reset_time)} | refresh=true font=Menlo size=13")
```

- 中文字体推荐 `PingFangSC`。
- 等宽数字/代码推荐 `Menlo`。
- 字号统一用 `13`，与 macOS 菜单栏风格一致。

#### `color`

```python
print("⚪️ CW | color=#999999")      # 离线灰色
print("🔴 CW 12s | color=#FF3B30")  # 录制红色
print("🎤 CW | color=#34C759")      # 在线绿色
print("请先运行 notion_todo_auth.py | color=#FF0000")
print(f"API 错误: {e.code} | color=red")
```

可用颜色：CSS 颜色名（如 `red`）或 `#RRGGBB` 十六进制。

#### `href`

```python
print("彩云天气 | href=https://www.caiyunapp.com/h5/ refresh=true")
print("Kimi Console | href=https://www.kimi.com/code/console")
print("Beta | href=https://www.kimi.com/code/beta")
print(f"Notion 数据库 | href=https://notion.so/{ds_id.replace('-', '')}")
```

#### `bash` + `paramN` + `terminal`

执行当前插件自身脚本是最常见的模式：

```python
script = plugin_path()
print(f"切换模式 | bash={sys.executable} param1={script} param2=--toggle terminal=false refresh=true")
```

打开外部程序：

```python
print(f"打开项目目录 | bash=open param1={CAPSWRITER_DIR} terminal=false")
```

执行简单命令：

```python
print("刷新 | refresh=true terminal=false bash=/usr/bin/python3 param1=-c param2='import time; time.sleep(1)'")
```

| 参数 | 说明 |
|------|------|
| `bash` | 要执行的命令或脚本路径 |
| `param1` ~ `paramN` | 依次传入的参数 |
| `terminal` | `false` 不打开终端；`true` 打开终端 |

#### `image`

用于显示内嵌图片（Base64 PNG/JPEG）：

```python
chart_b64 = base64.b64encode(png_data).decode()
print(f" | image={chart_b64} refresh=true")
```

本项目在 `caiyun_weather.10m.py` 里用纯标准库生成 2 小时降雨柱状图。

---

## 6. 特殊文本处理

### 6.1 转义 `|`

如果菜单文本本身需要显示 `|`，必须转义成 `\|`，否则 SwiftBar 会把它当成参数分隔符。

```python
def escape_swiftbar(s):
    return s.replace("|", "\\|").replace("\n", " ")
```

在 `notion_todo.2m.py` 中用于任务标题。

### 6.2 多行文本

SwiftBar 行内不支持换行，需把 `\n` 替换为空格或分段输出。

---

## 7. 可直接复用的模板

### 7.1 最小可用插件模板

```python
#!/usr/bin/env python3
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>

"""
SwiftBar 插件: XXX
刷新频率: 2 分钟
"""

import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()

def main():
    # 菜单栏标题
    print("🔔 标题 | refresh=true size=13")
    print("---")

    # 普通信息行
    print("信息项 | font=PingFangSC size=13 refresh=true")
    print("---")

    # 可点击动作：执行自身脚本
    print(f"点击我 | bash={sys.executable} param1={SCRIPT_PATH} param2=action terminal=false refresh=true")

    # 打开链接
    print("打开官网 | href=https://example.com refresh=true")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "action":
        print("动作已执行", file=sys.stderr)
    else:
        main()
```

### 7.2 带错误处理的标题 + 下拉菜单

```python
def main():
    try:
        data = fetch_data()
    except Exception as e:
        print("⚠️ 错误 | refresh=true color=red")
        print("---")
        print(f"{e} | color=red")
        return

    print(f"✅ 正常 | refresh=true size=13")
    print("---")
    print("详情...")
```

### 7.3 子菜单模板

```python
print("更多选项 | refresh=true")
print("-- 子项 1 | bash=... terminal=false refresh=true")
print("-- 子项 2 | href=https://example.com refresh=true")
```

### 7.4 状态颜色模板

```python
def status_color(ratio: float) -> str:
    if ratio >= 0.9:
        return "🔴"
    if ratio >= 0.7:
        return "🟡"
    return "🟢"
```

---

## 8. 未使用但值得了解的参数

写新插件时可能会用到：

| 参数 | 作用 |
|------|------|
| `length=20` | 截断文本长度 |
| `trim=true` | 自动去除首尾空格 |
| `alternate=true` | 按住 Option 时显示的替代项 |
| `dropdown=false` | 该项只显示在菜单栏，不进入下拉菜单 |
| `sfimage=star.fill` | 使用 SF Symbols 图标 |
| `templateImage=...` | 使用模板图片（可随深色模式变色） |
| `ansi=true` | 支持 ANSI 颜色转义 |
| `emojize=false` | 关闭 emoji 自动转换 |
| `symbolize=false` | 关闭符号自动转换 |

---

## 9. 统计汇总

| 类别 | 数量 |
|------|------|
| SwiftBar 插件文件 | 5 个 |
| 元数据指令 | 25 条 |
| `---` 分隔线 | 29 次 |
| `--` 子菜单项 | 4 次 |
| 带参数的输出行 | 48 行 |
| 参数总使用次数 | 96 次 |
| `bash` 动作 | 7 次 |
| `href` 动作 | 7 次 |
| `image` 图片显示 | 1 次 |

---

## 10. 参考链接

- [SwiftBar 官方文档](https://github.com/swiftbar/SwiftBar)
- [xbar 插件语法](https://xbarapp.com/docs/2021/03/01/introduction.html)（SwiftBar 兼容 xbar 语法）
