#!/usr/bin/env python3
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>

"""
SwiftBar 插件: Kimi Code 默认模型切换
安装:
1. 复制到 SwiftBar 插件目录:
   cp kimi_switch_model.2m.py "$HOME/Library/Application Support/SwiftBar/plugins/"
2. 确保可执行: chmod +x "$HOME/Library/Application Support/SwiftBar/plugins/kimi_switch_model.2m.py"

刷新频率: 2分钟

说明:
- 菜单栏显示当前模型简称: K2.7 / DS-V4 / DS-R1 等
- 下拉菜单列出 ~/.kimi-code/config.toml 中 [models.*] 定义的所有模型
- 点击模型名称即可切换 default_model
"""

import argparse
import os
import re
import sys

CONFIG_PATH = os.path.expanduser("~/.kimi-code/config.toml")

# 匹配 default_model = "..." 行
DEFAULT_MODEL_RE = re.compile(r'^(default_model\s*=\s*)"([^"]*)"', re.MULTILINE)

# 匹配 [models."..."] 或 [models.xxx] 节头
SECTION_MODEL_RE = re.compile(r'^\[models\.(?:")?([^"]+?)(?:")?\]\s*$')

# 匹配节内 key = "value"
KV_RE = re.compile(r'^(\w+)\s*=\s*"([^"]*)"')


def plugin_path() -> str:
    return os.path.abspath(sys.argv[0])


def read_config() -> tuple:
    """解析 config.toml，返回 (current_model_key, {model_key: (display_name, provider)})。
    纯文本解析，兼容 Python 3.9（无 tomllib）。
    """
    current = ""
    models_info = {}       # {key: (display_name, provider)}
    cur_model_key = None
    cur_display_name = None
    cur_provider = None

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith("#"):
                continue
            # 匹配 default_model 顶层 key
            m = DEFAULT_MODEL_RE.match(line)
            if m:
                current = m.group(2)
                continue
            # 匹配 [models.xxx] 节头
            m = SECTION_MODEL_RE.match(line_stripped)
            if m:
                # 保存上一个模型
                if cur_model_key:
                    models_info[cur_model_key] = (
                        cur_display_name or cur_model_key,
                        cur_provider or "",
                    )
                cur_model_key = m.group(1)
                cur_display_name = None
                cur_provider = None
                continue
            # 在 models 节内匹配 display_name / provider
            if cur_model_key:
                m = KV_RE.match(line_stripped)
                if m:
                    key = m.group(1)
                    val = m.group(2)
                    if key == "display_name" and not cur_display_name:
                        cur_display_name = val
                    elif key == "provider" and not cur_provider:
                        cur_provider = val

    # 文件末尾的最后一个模型
    if cur_model_key:
        models_info[cur_model_key] = (
            cur_display_name or cur_model_key,
            cur_provider or "",
        )

    return current, models_info


def set_default_model(model_key: str) -> None:
    """在配置文件中修改 default_model，保留注释和格式。"""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    new_content = DEFAULT_MODEL_RE.sub(
        rf'\1"{model_key}"',
        content,
        count=1,
    )

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)


def short_label(model_key: str) -> str:
    """为菜单栏生成极简短标签（≤6字符）。"""
    LABELS = {
        "kimi-code/kimi-for-coding": "K",
        "deepseek/deepseek-v4-flash": "V4F",
        "deepseek/deepseek-v4-pro": "V4P",
        "dsv4": "OV4F",
    }
    if model_key in LABELS:
        return LABELS[model_key]
    # fallback: 取最后一段，截断至 6 字符
    short = model_key.rsplit("/", 1)[-1]
    return short[:6]


def provider_label(provider: str) -> str:
    """将 provider key 转成简短可读标签。"""
    LABELS = {
        "managed:kimi-code": "Kimi Code",
        "deepseek": "DeepSeek",
        "openrouter": "OpenRouter",
        "openai": "OpenAI",
        "anthropic": "Anthropic",
    }
    return LABELS.get(provider, provider)


def print_menu(current: str, models_info: dict):
    script = plugin_path()
    label = short_label(current)
    print(f"{label} | size=13")
    print("---")
    cur_disp = models_info.get(current, (current, ""))[0]
    # print(f"当前: {cur_disp} | refresh=true")
    # print("---")

    # 按 provider 分组
    groups = {}
    for key, (disp_name, provider) in models_info.items():
        groups.setdefault(provider, []).append((key, disp_name))

    first_group = True
    for provider, items in groups.items():
        if not first_group:
            print("---")
        first_group = False
        for key, disp_name in items:
            if key == current:
                print(f"✓ {disp_name} | refresh=true")
            else:
                print(
                    f"{disp_name} | bash={sys.executable} "
                    f"param1={script} param2=--switch param3={key} "
                    f"terminal=false refresh=true"
                )

    print("---")
    print(f"编辑配置 | href=file://{CONFIG_PATH}")


def main():
    try:
        current, models_info = read_config()
    except FileNotFoundError:
        print("⚙? | refresh=true")
        print("---")
        print(f"未找到 {CONFIG_PATH} | color=red")
        return
    except Exception as e:
        print("⚙? | refresh=true")
        print("---")
        print(f"读取配置失败: {e} | color=red")
        return

    if not models_info:
        print("⚙? | refresh=true")
        print("---")
        print("配置文件中未定义 [models.*] 节 | color=red")
        return

    print_menu(current, models_info)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--switch", type=str, help="切换到指定模型 key")
    args = parser.parse_args()

    if args.switch:
        try:
            set_default_model(args.switch)
        except Exception as e:
            print(f"切换失败: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        main()
