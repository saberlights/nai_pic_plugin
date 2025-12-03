# NovelAI Web 图片生成插件

专用于 NovelAI Web API（如 std.loliyc.com）的图片生成插件。

**核心亮点**：
- 🚀 简单易用：使用 `/nai` 命令 + 自然语言描述即可生图，无需学习复杂语法
- 🤖 智能生成：LLM 自动将中文描述转换为优化的英文提示词
- 📸 自拍模式：支持自动添加 Bot 形象特征，生成个性化自拍图片
- ⚡ 自动撤回：可配置图片自动撤回，保护隐私

## 功能特性

- ✅ 支持 NovelAI Web API（std.loliyc.com 等网页代理接口）
- ✅ **智能提示词生成**：使用 LLM 自动将自然语言描述转换为优化的英文提示词
- ✅ **命令模式**：`/nai` 命令支持直接输入中文描述，无需掌握 NAI 语法
- ✅ **自拍模式**：支持自动添加自拍视角和 Bot 形象特征
- ✅ 使用 NAI 格式提示词（大括号权重语法）
- ✅ 文生图功能
- ✅ 支持多种采样器（k_euler, k_euler_ancestral 等）
- ✅ 支持自定义尺寸（竖图、方图或具体尺寸）
- ✅ **自动撤回功能**（可配置延迟时间，支持 `/nai on/off` 控制）
- ✅ **上下文管理**：智能判断是否继承上一轮提示词
- ❌ **不支持图生图**（仅文生图）

## 安装

1. 将插件文件夹复制到 `plugins/` 目录下
2. 安装依赖：`pip install requests`
3. 编辑 `config.toml` 配置文件（见下方配置说明）
4. 重启 MaiBot

## 快速开始

1. 配置 API 地址和密钥（在 `config.toml` 中）：
   ```toml
   [plugin]
   enabled = true

   [model]
   base_url = "https://std.loliyc.com"
   api_key = "your-api-key"
   ```

2. 使用 `/nai` 命令开始生图：
   ```
   /nai 画一张初音未来
   /nai 画一个蓝发女仆在花园里
   /nai 自拍，微笑
   ```

3. （可选）开启自动撤回功能：
   ```
   /nai on
   ```

## 配置

编辑 `config.toml` 文件：

```toml
[plugin]
enabled = true  # 启用插件

[model]
name = "NovelAI Web (std.loliyc.com)"
base_url = "https://std.loliyc.com"  # API 基础地址
api_key = "STD-lpUNBA03q1KPHuXKumz"  # API Token
model = "nai-diffusion-4-5-full"  # 模型名称

# NovelAI Web 专用参数
nai_endpoint = "/generate"  # API 端点
nai_size = "竖图"  # 图片尺寸
nai_cfg = 0.0
nai_noise_schedule = "karras"
sampler = "k_euler_ancestral"
num_inference_steps = 23
guidance_scale = 5.0
```

### 重要参数说明

| 参数 | 说明 | 示例 |
|------|------|------|
| `base_url` | API 基础地址 | `https://std.loliyc.com` |
| `api_key` | API Token（如需要） | `STD-lpUNBA03q1KPHuXKumz` |
| `model` | NovelAI 模型名称 | `nai-diffusion-4-5-full` |
| `nai_size` | 图片尺寸 | `竖图`、`方图`、`1024x1024` |
| `sampler` | 采样器 | `k_euler_ancestral` |
| `num_inference_steps` | 推理步数 | `23` |
| `guidance_scale` | 指导强度 | `5.0` |

### 自动撤回配置

```toml
[auto_recall]
enabled = false  # 是否默认启用自动撤回
delay_seconds = 5  # 撤回延迟时间（秒）
id_wait_seconds = 15  # 等待正式消息ID的最长时间（秒）
allowed_groups = []  # 允许使用自动撤回功能的会话白名单
# 示例：allowed_groups = ["qq:123456789", "telegram:987654321"]
```

### 提示词生成配置

插件默认始终使用内置 LLM 生成英文提示词（即使 Planner 提供了 `description` 也会优先改写）。你可以通过 `[prompt_generator]` 区域进行控制：

```toml
[prompt_generator]
model_name = ""          # 指定LLM模型代号，留空则自动选择
temperature = 0.2        # LLM温度
max_tokens = 200         # LLM输出上限
# prompt_template = """自定义模板，支持 <<USER_REQUEST>> 和 <<SELFIE_HINT>> 占位符"""
```

> `prompt_template` 可选；默认会使用与旧版 `description` 完全一致的生成规则，并且会把用户描述按照“主体→视角→服装→动作→环境→氛围→细节”的顺序重排成结构化文本，再交给 LLM。`<<STRUCTURED_REQUEST>>` 会注入这些槽位内容，`<<USER_REQUEST>>` 则是未经处理的原文，`<<SELFIE_HINT>>` 仅在自拍模式下插入额外指令。

## 使用方法

本插件支持两种使用方式：

### 1. 命令模式（推荐）

使用 `/nai` 命令，直接输入自然语言描述，插件会自动使用 LLM 生成符合 NovelAI 格式的提示词：

```
# 基础用法
用户: /nai 画一张初音未来
Bot: [自动生成提示词并生成图片]

# 详细描述
用户: /nai 画一个蓝发女仆在花园里坐着
Bot: [自动生成提示词并生成图片]

# 自拍模式（会自动添加自拍视角和Bot形象特征）
用户: /nai 自拍，微笑
Bot: [生成Bot自拍风格的图片]
```

**命令模式特点**：
- 自然语言描述即可，无需掌握 NAI 提示词语法
- 自动使用 LLM 将描述转换为优化的英文提示词
- 支持自拍模式（描述中包含"自拍"或"selfie"）
- 自动按照 NovelAI 推荐顺序整理提示词

### 2. 关键词触发模式

在对话中使用触发关键词，支持自然语言和手动 NAI 格式：

```
# 自然语言（自动转换）
用户: 画一个蓝发女仆
Bot: [自动生成提示词并生成图片]

# 手动 NAI 格式（高级用户）
用户: nai画 {{{masterpiece}}}, {{1girl}}, {{blue hair}}, {{maid outfit}}, sitting
Bot: [直接使用提示词生成图片]
```

### NAI 格式提示词说明

本插件使用 **NovelAI 专用格式**的提示词，使用大括号控制权重：

- `{{{{keyword}}}}` - 极高权重（4层大括号）
- `{{{keyword}}}` - 高权重（3层大括号）
- `{{keyword}}` - 中等权重（2层大括号）
- `keyword` - 常规权重（无括号）
- `[[keyword]]` - 降低权重（中括号）

**示例**：
```
{{{masterpiece}}}, {{blue hair}}, {{maid outfit}}, sitting in garden, sunlight
```

> **提示**：使用命令模式时，无需手动编写 NAI 格式提示词，LLM 会自动处理。

### 自动撤回功能

```
# 开启自动撤回
用户: /nai on
Bot: ✅ 已在群聊中开启NAI图片自动撤回功能
     📝 图片将在发送后 5 秒自动撤回
     💡 使用 /nai off 可关闭此功能

# 关闭自动撤回
用户: /nai off
Bot: ✅ 已在群聊中关闭NAI图片自动撤回功能
     💡 使用 /nai on 可重新开启
```

## 注意事项

1. **推荐使用命令模式**：使用 `/nai` 命令可以充分利用 LLM 自动生成提示词的功能，更加简单易用
2. **仅支持文生图**：本插件不支持图生图功能
3. **NAI 格式**：如果手动编写提示词，必须使用大括号权重语法，不支持圆括号 `(keyword:1.2)` 格式
4. **API 兼容性**：仅适用于 std.loliyc.com 等 NovelAI Web 代理接口
5. **图片格式**：支持返回 URL 或 base64 格式
6. **自拍模式配置**：如需使用自拍模式，建议在配置文件中设置 `selfie_prompt_add` 添加 Bot 的形象特征

## 常见问题

### Q: 推荐使用哪种方式？
A: 推荐使用 `/nai` 命令模式。它会自动使用 LLM 生成优化的提示词，无需掌握 NAI 提示词语法，更加简单易用。

### Q: 如何使用自拍模式？
A: 在 `/nai` 命令描述中包含"自拍"或"selfie"关键词即可，例如：`/nai 自拍，微笑`。自拍模式会自动添加配置文件中 `selfie_prompt_add` 设置的 Bot 形象特征和自拍视角。

### Q: 支持图生图吗？
A: 不支持，本插件仅支持文生图。如需图生图，请使用 `custom_pic_plugin` 插件。

### Q: 提示词格式是什么？
A: 如果使用 `/nai` 命令模式，无需关心格式，LLM 会自动处理。如果手动编写提示词，必须使用 NAI 格式（大括号权重），例如 `{{keyword}}`。不支持标准格式 `(keyword:1.2)`。

### Q: 如何设置图片尺寸？
A: 在配置文件中设置 `nai_size = "竖图"` 或 `"方图"`，也可以使用具体尺寸如 `"1024x1024"`。

### Q: 如何使用自动撤回功能？
A:
1. 在配置文件中设置 `auto_recall.enabled = true` 或使用命令 `/nai on` 开启
2. 配置 `delay_seconds` 设置撤回延迟时间
3. 如需限制使用范围，在 `allowed_groups` 中配置白名单
4. 使用 `/nai off` 可临时关闭当前会话的自动撤回

### Q: 如何自定义提示词生成行为？
A: 在配置文件的 `[prompt_generator]` 区域可以：
- 指定使用的 LLM 模型（`model_name`）
- 调整生成温度（`temperature`）
- 设置最大 token 数（`max_tokens`）
- 自定义提示词生成模板（`prompt_template`）

## 许可证

GPL-v3.0-or-later

## 作者

Rabbit

## 更新日志

### v1.0.0 (2025-12-03)
- 初始版本
- 支持 NovelAI Web API（std.loliyc.com 等代理接口）
- NAI 格式提示词支持（大括号权重语法）
- 文生图功能
- `/nai` 命令模式，支持自然语言描述
- LLM 智能提示词生成
- 自拍模式（自动添加 Bot 形象特征和自拍视角）
- 上下文管理（智能继承上一轮提示词）
- 自动撤回功能（支持 `/nai on/off` 控制）
- 支持多种采样器和自定义尺寸
