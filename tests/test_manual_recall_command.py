# -*- coding: utf-8 -*-
import os
import re
import sys
import types
import unittest
import asyncio
import importlib


PLUGIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAIBOT_ROOT = os.path.abspath(os.path.join(PLUGIN_DIR, "../.."))

if MAIBOT_ROOT not in sys.path:
    sys.path.insert(0, MAIBOT_ROOT)
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

dummy_logger_module = types.ModuleType("src.common.logger")


class _DummyLogger:
    def debug(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


def _get_logger(_name=None):
    return _DummyLogger()


dummy_logger_module.get_logger = _get_logger
sys.modules["src.common.logger"] = dummy_logger_module

src_package = types.ModuleType("src")
src_package.__path__ = [os.path.join(MAIBOT_ROOT, "src")]
sys.modules.setdefault("src", src_package)

src_chat_package = types.ModuleType("src.chat")
src_chat_package.__path__ = [os.path.join(MAIBOT_ROOT, "src", "chat")]
sys.modules.setdefault("src.chat", src_chat_package)

src_chat_utils_package = types.ModuleType("src.chat.utils")
src_chat_utils_package.__path__ = [os.path.join(MAIBOT_ROOT, "src", "chat", "utils")]
sys.modules.setdefault("src.chat.utils", src_chat_utils_package)

chat_utils_module = types.ModuleType("src.chat.utils.utils")
chat_utils_module.parse_platform_accounts = lambda _platforms: {}
sys.modules["src.chat.utils.utils"] = chat_utils_module

src_config_package = types.ModuleType("src.config")
src_config_package.__path__ = [os.path.join(MAIBOT_ROOT, "src", "config")]
sys.modules.setdefault("src.config", src_config_package)

config_module = types.ModuleType("src.config.config")
config_module.global_config = types.SimpleNamespace(
    bot=types.SimpleNamespace(
        platforms=[],
        qq_account="bot",
        telegram_account="",
        nickname="bot",
    )
)
sys.modules["src.config.config"] = config_module

plugin_system_module = types.ModuleType("src.plugin_system")
plugin_system_module.message_api = types.SimpleNamespace(get_recent_messages=lambda **kwargs: [])
sys.modules["src.plugin_system"] = plugin_system_module

plugin_system_base_package = types.ModuleType("src.plugin_system.base")
sys.modules["src.plugin_system.base"] = plugin_system_base_package

base_command_module = types.ModuleType("src.plugin_system.base.base_command")


class _DummyBaseCommand:
    pass


base_command_module.BaseCommand = _DummyBaseCommand
sys.modules["src.plugin_system.base.base_command"] = base_command_module

core_package = types.ModuleType("core")
core_package.__path__ = [os.path.join(PLUGIN_DIR, "core")]
sys.modules.setdefault("core", core_package)

core_commands_package = types.ModuleType("core.commands")
core_commands_package.__path__ = [os.path.join(PLUGIN_DIR, "core", "commands")]
sys.modules.setdefault("core.commands", core_commands_package)

core_mixins_package = types.ModuleType("core.mixins")
core_mixins_package.__path__ = [os.path.join(PLUGIN_DIR, "core", "mixins")]
sys.modules.setdefault("core.mixins", core_mixins_package)

core_utils_package = types.ModuleType("core.utils")
core_utils_package.__path__ = [os.path.join(PLUGIN_DIR, "core", "utils")]
sys.modules.setdefault("core.utils", core_utils_package)

core_constants_module = importlib.import_module("core.constants")
manual_recall_module = importlib.import_module("core.commands.nai_manual_recall_command")

NaiManualRecallCommand = manual_recall_module.NaiManualRecallCommand
NAI_PIC_IMAGE_DISPLAY_MARKER = core_constants_module.NAI_PIC_IMAGE_DISPLAY_MARKER


class _DummyMessageInfo:
    def __init__(self, message_id: str, additional_config=None):
        self.message_id = message_id
        self.additional_config = additional_config


class _DummyMessage:
    def __init__(self, message_id: str, additional_config=None, message_segment=None, reply=None):
        self.reply = reply
        self.message_info = _DummyMessageInfo(message_id=message_id, additional_config=additional_config)
        self.raw_message = None
        self.message_segment = message_segment
        self.chat_stream = type("ChatStream", (), {"stream_id": "stream_123"})()
        self.display_message = None
        self.processed_plain_text = "[imageurl:file:///a.png]"
        self.is_picid = False


class ManualRecallCommandTest(unittest.TestCase):
    def test_command_pattern_should_match_reply_prefixed_manual_recall(self):
        text = "[回复<xx> 的消息：[imageurl:file:///a.png]] /nai 撤回"
        self.assertIsNotNone(re.match(NaiManualRecallCommand.command_pattern, text))

    def test_extract_reply_message_id_should_not_use_self_message_id(self):
        """
        防止把“当前命令消息ID”当作引用目标（历史上容易误判）。
        """
        cmd = object.__new__(NaiManualRecallCommand)
        cmd.message = _DummyMessage(
            message_id="cmd_123",
            additional_config={"message_id": "cmd_123"},
            message_segment=None,
        )
        self.assertIsNone(cmd._extract_reply_message_id())

    def test_extract_reply_message_id_from_reply_segment(self):
        cmd = object.__new__(NaiManualRecallCommand)
        cmd.message = _DummyMessage(
            message_id="cmd_123",
            additional_config={},
            message_segment={"type": "reply", "data": "target_456"},
        )
        self.assertEqual(cmd._extract_reply_message_id(), "target_456")

    def test_validate_reply_target_should_use_reply_payload_fast_path(self):
        cmd = object.__new__(NaiManualRecallCommand)
        reply_msg = _DummyMessage(message_id="target_456")
        reply_msg.display_message = NAI_PIC_IMAGE_DISPLAY_MARKER
        cmd.message = _DummyMessage(
            message_id="cmd_123",
            additional_config={},
            message_segment={"type": "reply", "data": "target_456"},
            reply=reply_msg,
        )

        ok, resolved_id, reason = asyncio.run(cmd._validate_reply_target("target_456"))
        self.assertTrue(ok)
        self.assertEqual(resolved_id, "target_456")
        self.assertEqual(reason, "ok")


if __name__ == "__main__":
    unittest.main()
