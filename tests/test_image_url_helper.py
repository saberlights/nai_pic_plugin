# -*- coding: utf-8 -*-
import importlib
import os
import sys
import types
import unittest


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

core_package = types.ModuleType("core")
core_package.__path__ = [os.path.join(PLUGIN_DIR, "core")]
sys.modules.setdefault("core", core_package)

core_utils_package = types.ModuleType("core.utils")
core_utils_package.__path__ = [os.path.join(PLUGIN_DIR, "core", "utils")]
sys.modules.setdefault("core.utils", core_utils_package)

image_url_helper = importlib.import_module("core.utils.image_url_helper")


class ImageUrlHelperTest(unittest.TestCase):
    def test_detect_image_type_should_identify_png(self):
        self.assertEqual(
            image_url_helper._detect_image_type(b"\x89PNG\r\n\x1a\nrest"),
            "png",
        )

    def test_detect_image_type_should_identify_jpeg(self):
        self.assertEqual(
            image_url_helper._detect_image_type(b"\xff\xd8\xff\xe0rest"),
            "jpeg",
        )

    def test_detect_image_type_should_identify_webp(self):
        self.assertEqual(
            image_url_helper._detect_image_type(b"RIFF1234WEBPrest"),
            "webp",
        )

    def test_detect_image_type_should_fallback_to_png(self):
        self.assertEqual(image_url_helper._detect_image_type(b"unknown"), "png")


if __name__ == "__main__":
    unittest.main()
