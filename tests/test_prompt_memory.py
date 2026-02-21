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

render_previous_prompt_block = _mod.render_previous_prompt_block
extract_last_prompt_from_record_display = _mod.extract_last_prompt_from_record_display
LAST_PROMPT_RECORD_PREFIX = _mod.LAST_PROMPT_RECORD_PREFIX


class PromptMemoryTest(unittest.TestCase):
    def test_render_without_last_prompt_returns_empty(self):
        self.assertEqual(render_previous_prompt_block(None), "")
        self.assertEqual(render_previous_prompt_block(""), "")
        self.assertEqual(render_previous_prompt_block("   "), "")

    def test_render_with_last_prompt_contains_xml_block(self):
        block = render_previous_prompt_block("solo, 1girl, smile")
        self.assertIn("<previous_prompt_context>", block)
        self.assertIn("</previous_prompt_context>", block)
        self.assertIn("solo, 1girl, smile", block)
        self.assertIn("继承规则", block)
        self.assertIn("必须遵守", block)

    def test_render_block_does_not_contain_old_compose_patterns(self):
        """render_previous_prompt_block should not contain old compose patterns"""
        block = render_previous_prompt_block("solo, 1girl, smile")
        # Old compose_prompt_generator_request patterns should be absent
        self.assertNotIn("可被丢弃", block)
        self.assertNotIn("本次用户要求", block)
        self.assertNotIn("<<USER_REQUEST>>", block)

    def test_extract_last_prompt_from_record_display(self):
        display = f"{LAST_PROMPT_RECORD_PREFIX}\nsolo, 1girl, smile"
        self.assertEqual(extract_last_prompt_from_record_display(display), "solo, 1girl, smile")

    def test_extract_returns_none_for_non_matching_prefix(self):
        self.assertIsNone(extract_last_prompt_from_record_display("other: x"))


if __name__ == "__main__":
    unittest.main()
