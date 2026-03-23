# -*- coding: utf-8 -*-
import os
import unittest
import importlib.util


PLUGIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MOD_PATH = os.path.join(PLUGIN_DIR, "core", "utils", "random_scene_description.py")

_spec = importlib.util.spec_from_file_location("random_scene_description", MOD_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"无法加载模块: {MOD_PATH}")

_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

normalize_random_scene_description = _mod.normalize_random_scene_description


class RandomSceneDescriptionTest(unittest.TestCase):
    def test_normalize_common_danbooru_unfriendly_terms(self):
        text = "1男1女 水手服 站立后入 内射 失神 POV 天台"
        self.assertEqual(
            normalize_random_scene_description(text),
            "1个男性 1个女性 水手服 站立后入 内射 失神 第一人称视角 屋顶",
        )

    def test_normalize_punctuation_and_count_tokens(self):
        text = "2女，镜子自拍、俯视 / 床上"
        self.assertEqual(
            normalize_random_scene_description(text),
            "2个女性 镜子自拍 俯视镜头 在床上",
        )


if __name__ == "__main__":
    unittest.main()
