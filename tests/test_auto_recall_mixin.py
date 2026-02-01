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


from core.mixins.auto_recall_mixin import _extract_sender_user_id, _is_image_message, _text_looks_like_image


class _DummyUserInfo:
    def __init__(self, user_id: str):
        self.user_id = user_id


class _DummyMsg:
    def __init__(self, user_id: str, text: str):
        self.user_info = _DummyUserInfo(user_id)
        self.processed_plain_text = text
        self.display_message = None
        self.raw_message = None
        self.is_picid = False


class AutoRecallMixinUtilsTest(unittest.TestCase):
    def test_text_looks_like_image_prefix(self):
        self.assertTrue(_text_looks_like_image("[imageurl:file:///a.png]"))
        self.assertTrue(_text_looks_like_image("   [图片：xxx]"))
        self.assertFalse(_text_looks_like_image("[回复<xx> 的消息：[imageurl:file:///a.png]]"))

    def test_is_image_message_avoid_reply_false_positive(self):
        msg = _DummyMsg("bot", "[回复<xx> 的消息：[imageurl:file:///a.png]] 你好")
        self.assertFalse(_is_image_message(msg))

        msg2 = _DummyMsg("bot", "[imageurl:file:///a.png]")
        self.assertTrue(_is_image_message(msg2))

    def test_extract_sender_user_id(self):
        msg = _DummyMsg("123", "[imageurl:file:///a.png]")
        self.assertEqual(_extract_sender_user_id(msg), "123")

        msg_dict = {"message_info": {"user_info": {"user_id": "456"}}}
        self.assertEqual(_extract_sender_user_id(msg_dict), "456")


if __name__ == "__main__":
    unittest.main()

