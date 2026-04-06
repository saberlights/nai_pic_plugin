# BestNAI 图片生成插件

基于 BestNAI 的 OpenAI Chat Completions 兼容接口的文生图插件。

## 功能概览

- 使用 `/nai` 通过自然语言描述生图
- 使用 `/nai0` 直接输入英文 tag 生图
- 支持 NAI 模型切换、尺寸切换、提示词显示、自动撤回、管理员模式
- 使用内置 LLM 将中文描述转换为适合 NAI 的英文提示词
- 默认接入 BestNAI 新版接口：`POST /v1/chat/completions`

## 接口说明

插件当前使用的生图协议为：

- 地址：`https://你的域名/v1/chat/completions`
- 认证：`Authorization: Bearer <API_KEY>`
- 请求体：OpenAI Chat Completions 格式
- `messages[0].content`：生图参数 JSON 字符串

插件会自动把内部配置映射为类似下列结构：

```json
{
  "model": "nai-diffusion-4-5-full-anlas-0",
  "stream": false,
  "messages": [
    {
      "role": "user",
      "content": "{\"prompt\":\"1girl, masterpiece\",\"size\":[832,1216],\"steps\":23,\"scale\":5}"
    }
  ]
}
```

返回的 markdown data URI 图片会自动提取并发送第一张图。

## 安装与启用

1. 将插件放入 `plugins/nai_pic_plugin`
2. 安装依赖：`pip install -r requirements.txt`
3. 若使用 Python 3.13，保持 `requirements.txt` 中的版本下限，不要降级 `requests` 和 `numpy`
4. 配置 `config.toml`
5. 启用插件

`requirements.txt` 已包含 `openpyxl>=3.1.5`，这样 Python 3.13 下执行
`core/utils/tag_data_builder.py` 时也不会缺依赖。

## 推荐配置

```toml
[plugin]
enabled = true

[model]
name = "BestNAI"
base_url = "https://你的域名"
api_key = "你的API密钥"
default_model = "nai-diffusion-4-5-full-anlas-0"
nai_endpoint = "/v1/chat/completions"
```

如果你直接使用 `rinkoai.com`，可写成：

```toml
[model]
name = "BestNAI"
base_url = "https://rinkoai.com"
api_key = "你的API密钥"
default_model = "nai-diffusion-4-5-full-anlas-0"
nai_endpoint = "/v1/chat/completions"
nai_proxy_mode = "auto"
available_models = [
  "nai-diffusion-3-anlas-0",
  "nai-diffusion-3-furry-anlas-0",
  "nai-diffusion-4-curated-anlas-0",
  "nai-diffusion-4-full-anlas-0",
  "nai-diffusion-4-5-curated-anlas-0",
  "nai-diffusion-4-5-full-anlas-0"
]

[model_nai4_5]
nai_size = "竖图"
sampler = "k_euler_ancestral"
num_inference_steps = 23
guidance_scale = 5.0
default_size = "832x1216"
negative_prompt_add = ""
selfie_prompt_add = ""
nai_extra_params = { quality = true, uc_preset = "light", noise_schedule = "karras", image_format = "png" }
```

## 模型代号映射

`/nai set` 仍然兼容旧交互，但会切到新的模型名：

- `3` -> `nai-diffusion-3-anlas-0`
- `f3` -> `nai-diffusion-3-furry-anlas-0`
- `4` -> `nai-diffusion-4-full-anlas-0`
- `4.5` -> `nai-diffusion-4-5-full-anlas-0`

## 尺寸说明

插件内置常用尺寸映射：

- `竖` / `竖图` / `v` -> `832x1216`
- `横` / `横图` / `h` -> `1216x832`
- `方` / `方图` / `s` -> `1024x1024`

客户端会自动转为 BestNAI 所需的 `[宽, 高]` 数组。

## 常用命令

- `/nai 画一张初音未来`
- `/nai0 1girl, hatsune miku, masterpiece`
- `/nai set 4.5`
- `/nai size 横`
- `/nai pt on`
- `/nai nsfw on`
- `/nai on`
- `/nai help`

## 兼容说明

- 仅改为新的 BestNAI 文生图协议
- 旧配置项如 `nai_size`、`num_inference_steps`、`guidance_scale`、`nai_extra_params` 仍可继续使用
- `nai_artist_prompt` 会自动并入正向提示词
- 默认只提取并发送第一张图片
- 当前不支持图生图

## 返回解析

插件支持以下图片返回形式：

- `![image_0](data:image/png;base64,...)`
- `![image_0](https://...)`
- 纯 `data:image/...`
- 纯图片 URL
- 原始图片二进制响应

## 注意事项

- 建议超时至少 60 秒
- 推荐免费尺寸 `832x1216`，推荐步数 `23`
- `n_samples` 即使大于 1，插件当前也只发送第一张
- 若服务返回 400/401/402/429/502/503，插件会展示简化后的错误信息
