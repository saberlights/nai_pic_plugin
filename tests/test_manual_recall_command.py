# -*- coding: utf-8 -*-
import os
import sys
import unittest


PLUGIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAIBOT_ROOT = os.path.abspath(os.path.join(PLUGIN_DIR, "../.."))

if MAIBOT_ROOT not in sys.path:
    sys.path.insert(0, MAIBOT_ROOT)
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)


from core.commands.nai_manual_recall_command import NaiManualRecallCommand


class _DummyMessageInfo:
    def __init__(self, message_id: str, additional_config=None):
        self.message_id = message_id
        self.additional_config = additional_config


class _DummyMessage:
    def __init__(self, message_id: str, additional_config=None, message_segment=None):
        self.reply = None
        self.message_info = _DummyMessageInfo(message_id=message_id, additional_config=additional_config)
        self.raw_message = None
        self.message_segment = message_segment


class ManualRecallCommandTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

