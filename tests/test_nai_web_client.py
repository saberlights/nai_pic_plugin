# -*- coding: utf-8 -*-
import os
import sys
import types
import unittest
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

core_package = types.ModuleType("core")
core_package.__path__ = [os.path.join(PLUGIN_DIR, "core")]
sys.modules.setdefault("core", core_package)

core_clients_package = types.ModuleType("core.clients")
core_clients_package.__path__ = [os.path.join(PLUGIN_DIR, "core", "clients")]
sys.modules.setdefault("core.clients", core_clients_package)

nai_web_client_module = importlib.import_module("core.clients.nai_web_client")
NaiWebClient = nai_web_client_module.NaiWebClient


class NaiWebClientTest(unittest.TestCase):
    def test_normalize_size_should_support_legacy_alias_and_literal_size(self):
        self.assertEqual(NaiWebClient._normalize_size("竖图"), [832, 1216])
        self.assertEqual(NaiWebClient._normalize_size("1216x832"), [1216, 832])

    def test_extract_first_image_should_parse_markdown_data_uri(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": "![image_0](data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==)"
                    }
                }
            ]
        }

        self.assertEqual(
            NaiWebClient._extract_first_image(payload),
            "iVBORw0KGgoAAAANSUhEUg==",
        )

    def test_extract_error_message_from_standard_error_payload(self):
        payload = {
            "error": {
                "message": "Payload validation failed",
                "type": "invalid_request_error",
                "code": "bad_request",
            }
        }

        self.assertEqual(
            NaiWebClient._extract_error_message_from_payload(payload),
            "Payload validation failed",
        )

    def test_build_generation_params_should_map_legacy_fields(self):
        client = object.__new__(NaiWebClient)

        params = client._build_generation_params(
            prompt="1girl, masterpiece",
            artist_prompt="artist:test",
            negative_prompt="lowres",
            sampler="k_euler_ancestral",
            steps=23,
            guidance_scale=5.0,
            cfg_value=0.4,
            noise_schedule="karras",
            nocache=0,
            final_size="832x1216",
            extra_params={"quality": True, "image_format": "png"},
        )

        self.assertEqual(params["prompt"], "1girl, masterpiece, artist:test")
        self.assertEqual(params["negative_prompt"], "lowres")
        self.assertEqual(params["size"], [832, 1216])
        self.assertEqual(params["scale"], 5.0)
        self.assertEqual(params["cfg_rescale"], 0.4)
        self.assertTrue(params["quality"])
        self.assertEqual(params["image_format"], "png")


if __name__ == "__main__":
    unittest.main()
