# NovelAI Web 图片生成插件

专用于 NovelAI Web API（如 std.loliyc.com）的图片生成插件。

**核心亮点**：
- 🚀 简单易用：使用 `/nai` 命令 + 自然语言描述即可生图，无需学习复杂语法
- 🤖 智能生成：LLM 自动将中文描述转换为优化的英文提示词
- 🎨 智能画师串：LLM + Danbooru API 自动生成、验证和优化画师组合串
- 📸 自拍模式：LLM 自主判断自拍意图，支持 5 种自拍类型，自动添加 Bot 形象特征
- 🔄 提示词继承：三档继承机制（微调/换角色/新主题），支持 TTL 过期和上轮请求注入
- 🏷️ 图片打标：引用回复图片即可输出 NAI 格式的角色+标签 prompt
- ⚡ 自动撤回：可配置图片自动撤回，支持手动 `/nai 撤回`
- 🎭 模型切换：支持快速切换 NAI 3/4/4.5 等不同版本模型
- 🖼️ 尺寸切换：支持快速切换竖图/横图/方图
- 🔞 NSFW 过滤：支持开关 NSFW 内容过滤，灵活控制生成内容
- 🔒 权限控制：支持管理员模式，限制生图命令使用权限

## 功能特性

- ✅ 支持 NovelAI Web API（std.loliyc.com 等网页代理接口）
- ✅ **智能提示词生成**：使用 LLM 自动将自然语言描述转换为优化的英文提示词
- ✅ **提示词继承机制**：三档规则（微调/换角色/新主题）+ TTL 过期 + 上轮请求注入，重启后自动从数据库恢复
- ✅ **LLM 画师串生成**：通过 `/nai artgen` 使用 LLM + Danbooru API 智能生成画师组合串
- ✅ **随机画师串**：通过 `/nai artr` 随机生成画师风格组合
- ✅ **画师串迭代优化**：通过 `/nai artfix` 根据用户反馈迭代优化画师串
- ✅ **Danbooru API 集成**：自动验证画师标签有效性，显示画师稳定性评级
- ✅ **命令模式**：`/nai` 命令支持直接输入中文描述，无需掌握 NAI 语法
- ✅ **直接标签模式**：`/nai0` 命令直接使用英文标签生图，跳过 LLM 处理
- ✅ **自拍模式**：LLM 自主判断自拍意图（关键词触发 + 结构化输出 intent 字段），支持 5 种自拍类型（手机前置、镜子、高角度、低角度、合照）
- ✅ **图片打标**：`/打标` 引用回复图片，输出 NAI 格式的角色(作品)+tags prompt
- ✅ **手动撤回**：`/nai 撤回` 手动撤回插件生成的图片，支持引用回复指定消息
- ✅ **模型切换**：支持通过命令快速切换 NAI 3/f3/4/4.5 等模型（会话级别）
- ✅ **尺寸切换**：支持通过 `/nai size` 命令快速切换竖图/横图/方图
- ✅ **画师风格预设**：支持多套画师串预设，可自定义命名，通过配置文件设置
- ✅ **NSFW 内容过滤**：支持 `/nai nsfw on/off` 控制是否过滤 NSFW 内容
- ✅ **提示词显示**：支持 `/nai pt on/off` 控制是否显示生成的提示词
- ✅ **管理员权限控制**：支持开启管理员模式，限制生图命令仅管理员可用
- ✅ **分版本配置**：NAI V3/V4/V4.5 各版本独立配置参数和画师串
- ✅ **自定义 LLM 模型**：支持配置自定义 LLM 模型用于提示词和画师串生成
- ✅ **结构化输出**：支持 JSON 格式的 LLM 输出（version=3），包含 intent/continuity/global/people 字段
- ✅ **自拍外貌策略**：可配置自拍模式下的外貌标签处理策略（自动移除/保留/禁用）
- ✅ **提示词后处理**：支持轻量标签排序，优化提示词结构
- ✅ **自定义系统提示词**：通过 `[custom_prompt]` 注入额外的 LLM 指导规则
- ✅ 使用 NAI 格式提示词（大括号权重语法）
- ✅ 文生图功能
- ✅ 支持多种采样器（k_euler, k_euler_ancestral 等）
- ✅ 支持自定义尺寸（竖图、方图或具体尺寸）
- ✅ **自动撤回功能**（可配置延迟时间，支持 `/nai on/off` 控制）
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

3. 或使用 `/nai0` 直接输入英文标签（跳过 LLM）：
   ```
   /nai0 1girl, hatsune miku, smile, masterpiece
   ```

4. （可选）使用 LLM 智能生成画师串：
   ```
   /nai artgen 可爱萌系风格    # 根据风格描述生成
   /nai artr                   # 随机生成
   /nai artfix 线条太粗        # 迭代优化
   ```

5. （可选）切换模型/尺寸：
   ```
   /nai set 4.5    # 切换到 NAI 4.5
   /nai size 横    # 切换到横图
   ```

6. （可选）图片打标：
   ```
   /打标              # 引用回复一张图片，输出 NAI 格式 prompt
   ```

7. （可选）查看帮助：
   ```
   /nai help       # 查看所有命令帮助
   ```

## 配置

编辑 `config.toml` 文件：

```toml
[plugin]
enabled = true  # 启用插件

[model]
name = "NovelAI Web (std.loliyc.com)"
base_url = "https://std.loliyc.com"  # API 基础地址
api_key = "your-api-key"  # API Token
default_model = "nai-diffusion-4-5-full"  # 默认模型名称
```

### 打标配置（/打标）

`/打标` 会读取你"引用回复"的那条图片消息，对图片做 Danbooru/NAI 风格打标，并输出一行可直接复制给 NAI 的 prompt（角色(作品)+tags）。

推荐使用 `custom_model` 单独配置打标模型（完全独立于其它任务；`model_list` 需为支持图像输入的多模态模型）：

```toml
[tagger]
enabled = true

# 单独配置打标模型（推荐）
custom_model = { model_list = ["gemini-3-pro-preview"], max_tokens = 1200, temperature = 0.2, slow_threshold = 30.0 }

# max_tokens 是"请求上限"，最终是否截断取决于模型/提供商自身上限；建议 800~4096
```

### 分版本模型配置

插件支持为 NAI V3、V4、V4.5 分别配置参数。根据当前使用的模型自动加载对应配置：

```toml
# NAI V3 专用配置
[model_nai3]
nai_size = "832x1216"
sampler = "k_euler_ancestral"
num_inference_steps = 25
guidance_scale = 3.5
custom_prompt_add = "{masterpiece}, best quality, illustration"
negative_prompt_add = "..."
artist_presets = [
  { name = "风格1", prompt = "artist:example1, artist:example2" },
  { name = "风格2", prompt = "artist:example3, artist:example4" }
]

# NAI V4 专用配置
[model_nai4]
nai_size = "竖图"
sampler = "k_euler_ancestral"
num_inference_steps = 28
guidance_scale = 5.0
custom_prompt_add = ",masterpiece, best quality, absurdres"
negative_prompt_add = "..."
artist_presets = [
  { name = "风格组合1", prompt = "1.2::artist1::, 1.0::artist2::" },
  { name = "风格组合2", prompt = "1.5::artist3::, 1.0::artist4::" }
]

# NAI V4.5 专用配置
[model_nai4_5]
nai_size = "竖图"
sampler = "k_euler_ancestral"
num_inference_steps = 28
guidance_scale = 5.0
custom_prompt_add = ",masterpiece, best quality, absurdres"
negative_prompt_add = "..."
artist_presets = [
  { name = "channel风", prompt = "1.4::kazutake hazano::, 1.2::efe::, ..." },
  { name = "简笔朴素", prompt = "1.2::artist:shion(mirudakemann)::, ..." }
]
```

### 重要参数说明

| 参数 | 说明 | 示例 |
|------|------|------|
| `base_url` | API 基础地址 | `https://std.loliyc.com` |
| `api_key` | API Token（如需要） | `your-api-key` |
| `default_model` | NovelAI 默认模型名称 | `nai-diffusion-4-5-full` |
| `nai_size` | 图片尺寸 | `竖图`、`方图`、`1024x1024` |
| `sampler` | 采样器 | `k_euler_ancestral` |
| `num_inference_steps` | 推理步数 | `23` |
| `guidance_scale` | 指导强度 | `5.0` |
| `artist_presets` | 画师风格预设列表 | 见上方配置示例 |

> **注意**：`default_model` 参数是**默认模型**，会话中可通过 `/nai set` 命令临时切换。程序重启后会回退到此默认值。

### 自动撤回配置

```toml
[auto_recall]
enabled = false  # 是否默认启用自动撤回
delay_seconds = 5  # 撤回延迟时间（秒）
id_wait_seconds = 15  # 等待正式消息ID的最长时间（秒）
allowed_groups = []  # 允许使用自动撤回功能的会话白名单
# 示例：allowed_groups = ["qq:123456789", "telegram:987654321"]
```

### 管理员权限配置

```toml
[admin]
admin_users = ["584232670"]  # 管理员用户ID列表
default_admin_mode = false   # 是否默认启用管理员模式
```

**管理员命令**（仅管理员可用）：
- `/nai st` - 开启管理员模式（仅管理员可生图）
- `/nai sp` - 关闭管理员模式（所有人可生图）

**权限说明**：
- 开启管理员模式后，仅 `admin_users` 中的用户可使用 `/nai` 生图命令
- `default_admin_mode` 设置默认状态，可通过 `/nai st/sp` 动态切换
- 管理员模式是**会话级别**的（群聊/私聊独立配置）

### NSFW 内容过滤配置

```toml
[nsfw_filter]
enabled = false  # 是否默认启用NSFW内容过滤
filter_tags = "{{{{{nsfw}}}}}"  # NSFW过滤标签（高权重），启用时自动添加到负面提示词
```

**说明**：
- 开启后会在负面提示词中添加高权重的 NSFW 标签，禁止生成成人内容
- 同时会在 LLM 提示词生成时注入 NSFW 限制指令，从源头过滤
- 使用 `/nai nsfw on/off` 可在运行时切换（会话级别）

### 提示词显示配置

```toml
[prompt_show]
enabled = false  # 是否默认启用提示词显示（使用 /nai pt on|off 可在运行时切换）
hide_selfie_prompt_add = false  # 自拍模式下是否隐藏配置文件中的自拍补充提示词
```

### 提示词生成配置

插件默认始终使用内置 LLM 生成英文提示词（即使 Planner 提供了 `description` 也会优先改写）。你可以通过 `[prompt_generator]` 区域进行控制：

```toml
[prompt_generator]
model_name = ""          # 指定LLM模型代号，留空则自动选择
temperature = 0.2        # LLM温度
max_tokens = 500         # LLM输出上限
output_format = "json"   # LLM输出格式："json"（默认，结构化输出）或 "text"
selfie_appearance_policy = "auto"  # 自拍外貌标签策略："auto"（默认，固定自拍锚点优先）/"never"/"keep"
enable_programmatic_fallbacks = false  # 是否启用程序化提示词兜底修正，默认关闭
enforce_tag_order = false  # 是否启用轻量标签排序（人数/视角前置，year后置）
inherit_ttl = 3600       # 上一轮提示词继承的有效时间（秒），超过后不再继承。0=永不过期
# prompt_template = """自定义模板，支持 <<USER_REQUEST>> 和 <<SELFIE_HINT>> 占位符"""

# 自定义模型配置（可选）
# 如果配置了此项，将优先使用自定义模型，而不是系统模型
[prompt_generator.custom_model]
model_list = ["gpt-4o", "claude-3-5-sonnet"]  # 模型列表（按优先级排序）
max_tokens = 20000
temperature = 0.2
slow_threshold = 30.0
```

> `prompt_template` 可选。当前模板渲染默认支持 `<<USER_REQUEST>>`、`<<SELFIE_HINT>>`、`<<PREVIOUS_PROMPT>>`、`<<CURRENT_TIME_CONTEXT>>` 和 `<<CUSTOM_SYSTEM_PROMPT>>` 占位符；其中自拍身份/外貌锚点仍由程序通过 `selfie_prompt_add` 固定合并，不交给 LLM 自由改写。

**`output_format` 说明**：
- `json`（默认）：LLM 输出 JSON 结构（当前为 `version=3`，包含 `intent`、`continuity`、`global` 和 `people`），程序自动解析并渲染为最终 prompt。适合多人场景，也适合把"自拍/续图判断"交给 LLM
- `text`：LLM 直接输出逗号分隔的 tag 文本

**`selfie_appearance_policy` 说明**：
- `auto`（默认）：自拍模式下，程序会固定合并 `selfie_prompt_add` 作为 Bot 形象硬锚点；同时自动移除 LLM 随机生成的外貌标签（发色、发型、瞳色等）。用户明确描述外貌时不移除
- `never`：移除所有外貌标签（包括配置文件中的），仅保留动作、场景、氛围等
- `keep`：完全保留 LLM 输出，不做额外外貌裁剪
- `selfie_prompt_add` 的程序拼接仍然保留，用于固定自拍身份/外貌锚点；交给 LLM 的主要是自拍续图理解、场景继承和重点取舍
- `enable_programmatic_fallbacks = true` 时，才会启用代码侧的自拍穿搭继承、显式重点前置等兜底逻辑；默认关闭，优先依赖提示词和结构化输出

**`inherit_ttl` 说明**：
- 控制上一轮提示词的继承有效期，单位为秒
- 默认 3600（1 小时），超过后不再继承上一轮的提示词上下文
- 设为 0 表示永不过期

### 自定义系统提示词配置

```toml
[custom_prompt]
system_prompt = ""  # 自定义系统提示词，会添加到 LLM 提示词规则的最前面
```

**说明**：
- 自定义的系统提示词会注入到 LLM 提示词模板的 `<<CUSTOM_SYSTEM_PROMPT>>` 位置
- 可用于添加额外的生图规则、风格偏好或角色设定指导
- 仅在 Action（关键词触发）模式下生效，`/nai` 命令模式不使用此配置

### 画师串生成配置

LLM 画师串生成功能（`/nai artgen`、`/nai artr`、`/nai artfix`）的独立配置：

```toml
[artist_generator]
model_name = ""          # 画师串生成使用的LLM模型代号，留空则自动选择
temperature = 0.3        # LLM温度（风格描述模式）
random_temperature = 0.7 # 随机模式下的温度（/nai artr 命令）
max_tokens = 200         # LLM输出上限

# 自定义模型配置（可选）
[artist_generator.custom_model]
model_list = ["gpt-4o", "claude-3-5-sonnet"]
max_tokens = 200
temperature = 0.3
slow_threshold = 30.0
```

## 使用方法

本插件支持多种使用方式：

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
- 自拍意图由 LLM 自主判断（关键词仍可触发，但最终由结构化输出的 intent 字段确认）
- 支持 5 种自拍类型：手机前置、镜子自拍、高角度俯拍、低角度仰拍、合照
- 自动按照 NovelAI 推荐顺序整理提示词

### 2. 直接标签模式

使用 `/nai0` 命令，直接输入英文标签，跳过 LLM 处理，适合熟悉 NAI 提示词的高级用户：

```
# 直接使用英文标签
用户: /nai0 1girl, hatsune miku, smile, masterpiece, best quality
Bot: [直接使用提示词生成图片]

# 使用 NAI 权重语法
用户: /nai0 {{{masterpiece}}}, {{1girl}}, {{blue hair}}, maid outfit
Bot: [直接使用提示词生成图片]
```

**直接标签模式特点**：
- 跳过 LLM 处理，直接使用输入的标签
- 适合熟悉 NAI 提示词语法的用户
- 可以精确控制提示词内容和权重

### 3. LLM 画师串生成

使用 LLM + Danbooru API 智能生成画师组合串，支持风格描述、随机生成和迭代优化：

```
# 根据风格描述生成画师串
用户: /nai artgen 可爱萌系风格
Bot: 🎨 可爱萌系风格
     1.2::artist:example1::, 1.0::artist:example2::, ...

     📊 画师稳定性：
       • example1 [A] (5,234)
       • example2 [B] (1,823)

     💡 使用 /nai artfix <反馈> 可迭代优化

# 随机生成画师串
用户: /nai artr
Bot: 🎲 随机
     1.4::artist:random1::, 0.8::artist:random2::, ...

# 根据反馈迭代优化（需先生成画师串）
用户: /nai artfix 线条太粗，想要更细腻
Bot: 🔧 根据反馈「线条太粗，想要更细腻」优化

     原画师串：
     1.2::artist:old1::, ...

     优化后：
     1.3::artist:new1::, 0.9::artist:new2::, ...

     💡 继续使用 /nai artfix <反馈> 可进一步优化
```

**画师串生成特点**：
- `/nai artgen <风格描述>` - 根据风格描述智能生成画师组合
- `/nai artr` - 随机生成画师风格组合
- `/nai artfix <反馈>` - 根据用户反馈迭代优化上一次生成的画师串
- 自动通过 Danbooru API 搜索和验证画师标签
- 显示画师稳定性评级（基于帖子数量：A/B/C/D）
- 自动纠正拼写错误的画师名

### 4. 关键词触发模式

在对话中使用触发关键词，支持自然语言和手动 NAI 格式。此模式支持提示词继承和自定义系统提示词：

```
# 自然语言（自动转换）
用户: 画一个蓝发女仆
Bot: [自动生成提示词并生成图片]

# 手动 NAI 格式（高级用户）
用户: nai画 {{{masterpiece}}}, {{1girl}}, {{blue hair}}, {{maid outfit}}, sitting
Bot: [直接使用提示词生成图片]
```

### 5. 图片打标

使用 `/打标` 命令，引用回复一张图片，自动输出 NAI 格式的标签：

```
# 引用回复一张图片
用户: /打标
Bot: CHARACTER_TAG: hatsune_miku
     WORK_TAG: vocaloid
     TAG: 1girl, blue_hair, twintails, smile, ...
     BAD_TAG: ...
     PROMPT: hatsune miku (vocaloid), 1girl, blue hair, ...
     NEGATIVE: ...
```

**打标特点**：
- 引用回复图片即可使用，支持多种图片来源（消息段、附件、数据库）
- 使用 VLM（视觉语言模型）进行打标，需配置支持图像输入的模型
- 输出包含角色、作品、正向标签、负面标签和完整 prompt
- 可通过 `[tagger]` 配置独立的打标模型

### 6. 手动撤回

使用 `/nai 撤回` 手动撤回插件生成的图片：

```
# 撤回最近一张图片
用户: /nai 撤回
Bot: [撤回 Bot 最近发送的 NAI 图片]

# 引用回复指定图片撤回
用户: （引用回复某张图片）/nai 撤回
Bot: [撤回指定的 NAI 图片]
```

**手动撤回特点**：
- 仅撤回本插件生成的图片（通过标记识别），不会误撤其他消息
- 支持引用回复指定撤回某张图片
- 不引用时自动查找最近发送的插件图片
- 自动处理临时消息 ID 到正式平台 ID 的转换

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

### NSFW 内容过滤功能

支持在群聊或私聊中开关 NSFW 内容过滤：

```
# 开启 NSFW 过滤（禁止生成成人内容）
用户: /nai nsfw on
Bot: ✅ 已在群聊中开启NSFW内容过滤
     🔒 生成的图片将避免包含成人内容
     💡 使用 /nai nsfw off 可关闭过滤

# 关闭 NSFW 过滤
用户: /nai nsfw off
Bot: ✅ 已在群聊中关闭NSFW内容过滤
     🔓 生成的图片将不受NSFW限制
     💡 使用 /nai nsfw on 可重新开启

# 查看当前状态
用户: /nai nsfw
Bot: 当前NSFW过滤状态: 已关闭
```

**NSFW 过滤说明**：
- 开启后会在负面提示词中添加高权重 NSFW 标签
- 同时在 LLM 提示词生成阶段注入限制指令，从源头过滤
- 是**会话级别**的（每个群聊/私聊独立设置）
- 管理员模式开启时，仅管理员可操作

### 自动撤回功能

支持在群聊或私聊中自动撤回生成的图片：

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

### 尺寸切换功能

支持快速切换图片尺寸（会话级别）：

```
# 查看当前尺寸和可用尺寸列表
用户: /nai size
Bot: 当前使用默认配置尺寸

     可用尺寸:
     竖/v - 竖图 (832x1216)
     横/h - 横图 (1216x832)
     方/s - 方图 (1024x1024)

     使用方法: /nai size <尺寸代号>

# 切换到横图
用户: /nai size 横
Bot: ✅ 已切换到: 横图
     尺寸: 1216x832

# 切换到方图
用户: /nai size s
Bot: ✅ 已切换到: 方图
     尺寸: 1024x1024
```

**注意事项**：
- 尺寸切换是**会话级别**的（每个群聊/私聊独立设置）
- 尺寸设置是**运行时临时的**，程序重启后会回退到配置文件中的默认尺寸
- 所有用户都可以使用 `/nai size` 命令（管理员模式开启时除外）

### 提示词显示功能

支持在生图时显示生成的提示词：

```
# 开启提示词显示
用户: /nai pt on
Bot: ✅ 已开启提示词显示

# 关闭提示词显示
用户: /nai pt off
Bot: ✅ 已关闭提示词显示
```

开启后，每次生图时会先显示 LLM 生成的提示词，方便调试和学习。

### 模型切换功能

支持快速切换 NAI 不同版本的模型（会话级别）：

```
# 查看当前模型和可用模型列表
用户: /nai set
Bot: 当前使用默认模型: nai-diffusion-4-5-full

     可用模型:
     3 - nai-diffusion-3
     f3 - nai-diffusion-3-furry
     4 - nai-diffusion-4-full
     4.5 - nai-diffusion-4-5-full

     使用方法: /nai set <模型代号>

# 切换到 NAI 4.5
用户: /nai set 4.5
Bot: ✅ 已切换到模型: nai-diffusion-4-5-full
     代号: 4.5

# 切换到 NAI 3
用户: /nai set 3
Bot: ✅ 已切换到模型: nai-diffusion-3
     代号: 3

# 切换到 furry 模型
用户: /nai set f3
Bot: ✅ 已切换到模型: nai-diffusion-3-furry
     代号: f3
```

**注意事项**：
- 模型切换是**会话级别**的（每个群聊/私聊独立设置）
- 模型设置是**运行时临时的**，程序重启后会回退到配置文件中的默认模型
- 所有用户都可以使用 `/nai set` 命令（不需要管理员权限）

### 管理员权限控制

支持开启管理员模式，限制只有管理员可以使用生图命令：

```
# 开启管理员模式（仅管理员可执行）
用户: /nai st
Bot: ✅ 已在群聊中开启NAI管理员模式
     🔒 现在仅管理员可使用 /nai 生图命令
     💡 使用 /nai sp 可关闭此模式

# 关闭管理员模式（仅管理员可执行）
用户: /nai sp
Bot: ✅ 已在群聊中关闭NAI管理员模式
     🔓 现在所有人都可使用 /nai 生图命令
     💡 使用 /nai st 可重新开启

# 普通用户在管理员模式下尝试生图
用户: /nai 画一张初音未来
Bot: ❌ 当前会话已开启管理员模式，仅管理员可使用此命令
```

**权限说明**：
- `/nai st` 和 `/nai sp` 命令仅管理员可用
- 管理员模式是**会话级别**的（每个群聊/私聊独立配置）
- 在配置文件中设置 `admin.admin_users` 指定管理员用户ID
- 在配置文件中设置 `admin.default_admin_mode` 可配置默认状态

## 命令速查表

| 命令 | 说明 |
|------|------|
| `/nai <描述>` | 自然语言描述生图（LLM 自动生成提示词） |
| `/nai0 <标签>` | 直接使用英文标签生图（跳过 LLM） |
| `/nai set [代号]` | 查看/切换模型（3/f3/4/4.5） |
| `/nai size [代号]` | 查看/切换尺寸（竖/横/方） |
| `/nai artgen <风格>` | LLM 根据风格描述生成画师串 |
| `/nai artr` | 随机生成画师串 |
| `/nai artfix <反馈>` | 迭代优化上一次的画师串 |
| `/nai nsfw [on/off]` | 查看/切换 NSFW 内容过滤 |
| `/nai pt on/off` | 开关提示词显示 |
| `/nai on/off` | 开关自动撤回 |
| `/nai 撤回` | 手动撤回插件生成的图片（支持引用回复指定消息） |
| `/nai st/sp` | 开关管理员模式（仅管理员） |
| `/nai help` | 查看帮助信息 |
| `/打标` | 引用回复图片进行打标，输出 NAI 格式的 prompt（角色(作品)+tags） |

## 注意事项

1. **推荐使用命令模式**：使用 `/nai` 命令可以充分利用 LLM 自动生成提示词的功能，更加简单易用
2. **仅支持文生图**：本插件不支持图生图功能
3. **NAI 格式**：如果手动编写提示词，必须使用大括号权重语法，不支持圆括号 `(keyword:1.2)` 格式
4. **API 兼容性**：仅适用于 std.loliyc.com 等 NovelAI Web 代理接口
5. **图片格式**：支持返回 URL 或 base64 格式
6. **自拍模式配置**：如需使用自拍模式，建议在配置文件中设置 `selfie_prompt_add` 添加 Bot 的形象特征
7. **动作触发边界**：像"你最喜欢的衣服是什么""你平时会穿什么""你喜欢JK还是连衣裙"这类聊天/提问默认不应触发生图，只有明确索要视觉展示时才适合触发
8. **画师串生成**：`/nai artgen` 需要网络访问 Danbooru API（danbooru.donmai.us），请确保网络可达
9. **图片打标**：`/打标` 命令需要配置支持图像输入的多模态模型（如 Gemini），建议在 `[tagger]` 中单独配置

## 常见问题

### Q: 推荐使用哪种方式？
A: 推荐使用 `/nai` 命令模式。它会自动使用 LLM 生成优化的提示词，无需掌握 NAI 提示词语法，更加简单易用。

### Q: 如何使用直接标签模式？
A: 使用 `/nai0` 命令，直接输入英文标签，例如：`/nai0 1girl, hatsune miku, smile`。这种模式跳过 LLM 处理，适合熟悉 NAI 提示词的用户。

### Q: 如何使用 LLM 画师串生成？
A: 三个命令：
- `/nai artgen <风格描述>` - 根据中文风格描述生成画师串（如"可爱萌系"、"厚涂风"等）
- `/nai artr` - 随机生成画师串
- `/nai artfix <反馈>` - 对上次生成的画师串进行迭代优化（如"线条太粗"、"颜色太淡"等）

生成的画师串会通过 Danbooru API 验证，并显示每位画师的稳定性评级。

### Q: 如何切换图片尺寸？
A: 使用 `/nai size <尺寸代号>` 命令：
- `竖` 或 `v` - 竖图 (832x1216)
- `横` 或 `h` - 横图 (1216x832)
- `方` 或 `s` - 方图 (1024x1024)

尺寸切换是会话级别的，重启后会恢复到配置文件中的默认尺寸。

### Q: 如何控制 NSFW 内容？
A: 使用 `/nai nsfw on` 开启 NSFW 过滤（禁止生成成人内容），使用 `/nai nsfw off` 关闭过滤。也可在配置文件 `[nsfw_filter]` 中设置默认状态。

### Q: 如何显示生成的提示词？
A: 使用 `/nai pt on` 开启提示词显示，生图时会先显示 LLM 生成的提示词。使用 `/nai pt off` 关闭。

### Q: 如何查看所有命令帮助？
A: 使用 `/nai help` 命令查看完整的命令帮助信息。

### Q: 如何使用自拍模式？
A: 自拍意图现在由 LLM 自主判断。在描述中包含自拍相关内容即可触发，常见触发方式：
- 基础词：自拍、selfie、镜子、mirror
- 动作词：手机拍、前置相机、自拍杆、合照、合影
- 角度词：俯拍、仰拍、高角度、低角度
- 其他：拍照、照镜子、给自己拍等

使用 JSON 结构化输出时，LLM 会在 `intent` 字段中明确标注 `selfie`，程序根据此字段确认自拍意图。

支持 5 种自拍类型，LLM 会根据描述自动选择最合适的类型：
1. 手机前置自拍（默认）
2. 镜子自拍
3. 高角度俯拍
4. 低角度仰拍
5. 合照自拍

自拍模式会自动添加配置文件中 `selfie_prompt_add` 设置的 Bot 形象特征，这部分是程序固定锚点。可通过 `selfie_appearance_policy` 配置外貌标签的处理策略；自拍续图时的场景继承、构图变化、重点取舍主要交给 LLM 判断。

### Q: 提示词继承机制是什么？
A: 在关键词触发模式（Action）下，插件支持三档提示词继承：
- **微调**（keep/adjust）：延续上一轮的主体、穿搭、场景，只改动作/镜头/局部
- **换角色**（switch）：切换场景或穿搭，但可保留构图和光线思路
- **新主题**（new）：完全独立的新请求，不继承上一轮内容

继承行为由 LLM 在结构化输出的 `continuity` 字段中决定。上一轮的请求文本也会注入给 LLM，帮助做 diff 推理。继承有 TTL 过期机制（默认 1 小时），超时后自动视为新主题。重启后自动从数据库恢复上一轮上下文。

> 注意：`/nai` 命令模式不使用提示词继承，每次都是独立请求。

### Q: 什么情况下不会自动触发生图动作？
A: 普通聊天、知识问答、偏好提问、设定讨论默认都不应触发生图。例如：
- `你最喜欢的衣服是什么`
- `你平时会穿什么`
- `你喜欢JK还是连衣裙`
- `你觉得黑丝怎么样`

这类输入默认应先文字回复。只有用户明确索要视觉展示、自拍、照片或继续上一轮发图话题时，才适合触发生图动作。

### Q: 如何使用图片打标？
A: 引用回复一张图片，然后发送 `/打标`。Bot 会使用 VLM 模型识别图片内容，输出角色名(作品名)和 Danbooru 风格标签。需要在 `[tagger]` 配置中设置支持图像输入的模型。

### Q: 如何手动撤回图片？
A: 使用 `/nai 撤回` 命令。不引用时自动撤回最近一张插件生成的图片；引用回复某张图片则撤回指定图片。仅能撤回本插件生成的图片。

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
- 配置自定义 LLM 模型（`[prompt_generator.custom_model]`）
- 设置提示词继承过期时间（`inherit_ttl`）

### Q: 如何切换生图模型？
A: 使用 `/nai set <模型代号>` 命令，支持的模型代号：
- `3` - NAI Diffusion 3
- `f3` - NAI Diffusion Furry 3
- `4` - NAI Diffusion 4
- `4.5` - NAI Diffusion 4.5

模型切换是会话级别的，重启后会恢复到配置文件中的默认模型。

### Q: 如何启用管理员模式？
A:
1. 在配置文件中设置 `admin.admin_users` 添加管理员用户ID
2. 管理员使用 `/nai st` 命令开启管理员模式
3. 使用 `/nai sp` 可关闭管理员模式
4. 或在配置文件中设置 `admin.default_admin_mode = true` 默认开启

## 项目结构

```
nai_pic_plugin/
├── plugin.py              # 插件入口，注册组件
├── config.toml            # 配置文件
├── __init__.py            # 模块初始化
├── _manifest.json         # 插件清单
├── generated_images/      # 生成的图片缓存目录
└── core/
    ├── constants.py               # 插件常量（图片标记等）
    ├── actions/                   # 动作组件（关键词触发生图）
    │   └── nai_pic_action.py
    ├── commands/                  # 命令组件
    │   ├── nai_draw_command.py        # /nai 命令（LLM 生图）
    │   ├── nai_0_draw_command.py      # /nai0 命令（直接标签生图）
    │   ├── nai_artist_command.py      # /nai artgen/artr/artfix 命令（画师串生成）
    │   ├── nai_admin_command.py       # /nai st/sp/set/size/art 命令
    │   ├── nai_recall_command.py      # /nai on/off 命令（自动撤回开关）
    │   ├── nai_manual_recall_command.py # /nai 撤回 命令（手动撤回图片）
    │   ├── nai_nsfw_command.py        # /nai nsfw 命令（NSFW过滤）
    │   ├── nai_prompt_show_command.py # /nai pt 命令（提示词显示）
    │   └── nai_tag_command.py         # /打标 命令（图片打标）
    ├── clients/                   # API 客户端
    │   └── nai_web_client.py
    ├── mixins/                    # 混入类（自动撤回、模型配置等）
    │   ├── model_config_mixin.py
    │   └── auto_recall_mixin.py
    ├── rules/                     # 提示词模板和规则
    │   ├── prompt_rules.py            # LLM 提示词生成规则（SFW/NSFW × text/JSON）
    │   ├── artist_rules.py            # 画师串生成规则
    │   └── selfie_rules.py            # 自拍模式规则（LLM 意图判断、5类型）
    ├── services/                  # 服务层
    │   ├── session_state.py           # 会话状态管理
    │   ├── prompt_generator.py        # 提示词生成服务
    │   ├── prompt_memory.py           # 提示词继承与记忆（三档规则、TTL、持久化）
    │   └── image_generator.py         # 图片生成服务
    └── utils/                     # 工具类
        ├── danbooru_api.py            # Danbooru API 集成
        ├── image_url_helper.py        # 图片处理工具
        ├── tagger_utils.py            # 打标辅助工具（图片提取、格式检测）
        ├── prompt_output_parser.py    # LLM 结构化输出解析（version 1-3）
        └── prompt_postprocessor.py    # 提示词后处理（排序、外貌移除）
```

## 许可证

GPL-v3.0-or-later

## 作者

Rabbit

## 更新日志

### v1.5.0 (2025-02-10)
- 新增 **提示词继承机制**：三档规则（微调/换角色/新主题）+ TTL 过期 + 上轮请求注入
- 新增 **LLM 自主判断自拍意图**：自拍检测从纯关键词匹配改为 LLM 结构化输出的 intent 字段判断
- 新增 `/nai 撤回` **手动撤回命令**：支持引用回复指定图片或自动撤回最近图片，仅限插件图片
- 新增 `/打标` **图片打标命令**：引用回复图片输出 NAI 格式的角色+标签 prompt，支持独立 VLM 模型配置
- 新增 `[custom_prompt]` **自定义系统提示词配置**：可注入额外的 LLM 生图规则
- 新增 `[tagger]` **打标配置区域**：独立配置打标模型、温度、max_tokens
- 新增 `inherit_ttl` 配置项：控制提示词继承的过期时间
- 新增 `constants.py`：插件图片标记常量，用于识别插件生成的图片
- 新增 `prompt_memory.py`：提示词继承与记忆服务，支持重启后从数据库恢复
- 新增 `tagger_utils.py`：打标辅助工具（图片提取、base64处理、格式检测）
- 优化提示词生成规则：更精细的服装收敛、袜类标准化、构图与视觉重点联动
- 优化插件触发条件：更自然的触发边界，避免普通聊天误触发
- 优化自动撤回：手动撤回仅限插件图片，等待真实平台消息 ID

### v1.4.0 (2025-02-03)
- 新增自拍模式增强：支持 24 种触发关键词、5 种自拍类型（手机前置、镜子、高角度、低角度、合照）
- 新增 JSON 结构化输出格式（`output_format = "json"`），提升多人场景解析准确性
- 新增自拍外貌标签策略配置（`selfie_appearance_policy`）：auto/never/keep 三种模式
- 新增轻量标签排序功能（`enforce_tag_order`）：人数/视角前置、year 后置
- 新增提示词显示隐藏自拍补充选项（`hide_selfie_prompt_add`）
- 新增 `selfie_rules.py`：独立的自拍模式规则模块
- 新增 `prompt_output_parser.py`：LLM 结构化输出解析工具
- 新增 `prompt_postprocessor.py`：提示词后处理工具（排序、外貌标签移除）
- 优化 LLM 提示词模板：移除固定词组库，改为更灵活的标签知识指导
- 优化多人 | 分段格式处理逻辑
- 移除提示词默认 1000 字符截断限制

### v1.3.0 (2025-01-28)
- 新增 `/nai artgen <风格描述>` LLM 智能画师串生成功能
- 新增 `/nai artr` 随机画师串生成功能
- 新增 `/nai artfix <反馈>` 画师串迭代优化功能
- 新增 Danbooru API 集成，自动搜索、验证和纠正画师标签
- 新增画师稳定性评级显示（A/B/C/D，基于帖子数量）
- 新增 `/nai nsfw on/off` NSFW 内容过滤功能
- 新增 `[nsfw_filter]` 配置区域
- 新增 `[artist_generator]` 独立画师串生成配置区域
- 重构架构：拆分为 actions/commands/clients/mixins/rules/services/utils 模块

### v1.2.0 (2025-01-23)
- 新增 `/nai0` 直接标签模式，跳过 LLM 处理
- 新增 `/nai size` 尺寸切换命令（竖/横/方）
- 新增 `/nai art` 画师风格切换命令
- 新增 `/nai pt on/off` 提示词显示控制命令
- 新增 `/nai help` 帮助命令
- 新增分版本模型配置（NAI V3/V4/V4.5 独立配置）
- 新增画师串预设命名功能
- 新增自定义 LLM 模型配置支持
- 优化提示词生成模板

### v1.1.0 (2025-12-04)
- 新增模型切换功能（`/nai set` 命令）
- 新增管理员权限控制（`/nai st/sp` 命令）
- 支持会话级别的模型选择
- 支持会话级别的管理员模式控制
- 修复 SSL 证书验证问题

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
