# -*- coding: utf-8 -*-
import os
import unittest
import importlib.util


PLUGIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MOD_PATH = os.path.join(PLUGIN_DIR, "core", "rules", "selfie_rules.py")

_spec = importlib.util.spec_from_file_location("selfie_rules", MOD_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"无法加载模块: {MOD_PATH}")

_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

merge_selfie_prompt = _mod.merge_selfie_prompt


class SelfieRulesTest(unittest.TestCase):
    def test_merge_selfie_prompt_keeps_fixed_anchor_and_removes_conflicts(self):
        generated = "selfie, smile, black hair, blue eyes, bedroom"
        anchor = "pink hair, green eyes, hairclip"
        merged = merge_selfie_prompt(generated, anchor)

        self.assertIn("pink hair", merged)
        self.assertIn("green eyes", merged)
        self.assertIn("hairclip", merged)
        self.assertNotIn("black hair", merged)
        self.assertNotIn("blue eyes", merged)
        self.assertTrue(merged.startswith("selfie, smile, pink hair, green eyes, hairclip"))

    def test_merge_selfie_prompt_with_empty_anchor_returns_original(self):
        generated = "selfie, smile, bedroom"
        self.assertEqual(merge_selfie_prompt(generated, ""), generated)


if __name__ == "__main__":
    unittest.main()
