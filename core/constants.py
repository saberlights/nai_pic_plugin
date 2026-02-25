# -*- coding: utf-8 -*-
"""
本插件内部常量。

注意：这里的常量用于“仅撤回本插件发送的图片”的识别标记。
标记写入数据库字段 display_message，不会在群里直接显示。
"""

# 用于标记“本插件发送的图片消息”的 display_message
# 只要该字段包含此标记，即可认为是本插件发送的图片（供 /nai 撤回 等逻辑识别）
NAI_PIC_IMAGE_DISPLAY_MARKER = "[nai_pic_plugin:image]"

