# -*- coding: utf-8 -*-
import os
import unittest
import importlib.util


PLUGIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MOD_PATH = os.path.join(PLUGIN_DIR, "core", "services", "prompt_memory.py")

_spec = importlib.util.spec_from_file_location("prompt_memory", MOD_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"无法加载模块: {MOD_PATH}")

_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

compose_prompt_generator_request = _mod.compose_prompt_generator_request
extract_last_prompt_from_record_display = _mod.extract_last_prompt_from_record_display
LAST_PROMPT_RECORD_PREFIX = _mod.LAST_PROMPT_RECORD_PREFIX


class PromptMemoryTest(unittest.TestCase):
    def test_compose_without_last_prompt(self):
        out = compose_prompt_generator_request("画一张初音未来", None)
        self.assertEqual(out, "画一张初音未来")

    def test_compose_with_last_prompt_contains_markers(self):
        out = compose_prompt_generator_request("把背景换成夜景", "solo, 1girl, smile")
        self.assertIn("<previous_prompt>", out)
        self.assertIn("solo, 1girl, smile", out)
        self.assertIn("把背景换成夜景", out)
        self.assertIn("继承规则", out)

    def test_extract_last_prompt_from_record_display(self):
        display = f"{LAST_PROMPT_RECORD_PREFIX}\nsolo, 1girl, smile"
        self.assertEqual(extract_last_prompt_from_record_display(display), "solo, 1girl, smile")

    def test_extract_returns_none_for_non_matching_prefix(self):
        self.assertIsNone(extract_last_prompt_from_record_display("other: x"))


if __name__ == "__main__":
    unittest.main()

