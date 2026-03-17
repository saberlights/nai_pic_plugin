# -*- coding: utf-8 -*-
import os
import unittest
import importlib.util


PLUGIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PARSER_PATH = os.path.join(PLUGIN_DIR, "core", "utils", "prompt_output_parser.py")

_spec = importlib.util.spec_from_file_location("prompt_output_parser", PARSER_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"无法加载模块: {PARSER_PATH}")

_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

parse_prompt_from_structured_output = _mod.parse_prompt_from_structured_output
parse_structured_prompt_payload = _mod.parse_structured_prompt_payload


class PromptOutputParserTest(unittest.TestCase):
    def test_parse_single_json(self):
        text = '{"format":"single","prompt":"solo, 1girl, smile","version":1}'
        self.assertEqual(parse_prompt_from_structured_output(text), "solo, 1girl, smile")

    def test_parse_multi_json_with_newlines(self):
        text = '{"format":"multi","prompt":"2girls, rain\\\\n|girl a, hug\\\\n|girl b, hug","version":1}'
        self.assertEqual(parse_prompt_from_structured_output(text), "2girls, rain\n|girl a, hug\n|girl b, hug")

    def test_parse_json_in_code_fence(self):
        text = '```json\n{"format":"single","prompt":"a, b","version":1}\n```'
        self.assertEqual(parse_prompt_from_structured_output(text), "a, b")

    def test_parse_json_with_noise(self):
        text = 'OK\\n{"prompt":"x, y","format":"single","version":1}\\nThanks'
        self.assertEqual(parse_prompt_from_structured_output(text), "x, y")

    def test_parse_fail_returns_none(self):
        self.assertIsNone(parse_prompt_from_structured_output("not json"))

    def test_parse_v2_arrays_single(self):
        text = '{"version":2,"format":"single","global":["solo","1girl","smile"],"people":[]}'
        self.assertEqual(parse_prompt_from_structured_output(text), "solo, 1girl, smile")

    def test_parse_v2_arrays_single_with_one_person(self):
        text = '{"version":2,"format":"single","global":["solo","1girl","cityscape"],"people":[["{roxy migurdia (mushoku tensei)}","standing"]]}'
        self.assertEqual(
            parse_prompt_from_structured_output(text),
            "solo, 1girl, cityscape, {roxy migurdia (mushoku tensei)}, standing"
        )

    def test_parse_v2_arrays_multi(self):
        text = (
            '{"version":2,"format":"multi",'
            '"global":["2girls","street","day","year 2024"],'
            '"people":[["girl a","smile"],["girl b","smile"]]}'
        )
        self.assertEqual(
            parse_prompt_from_structured_output(text),
            "2girls, street, day, year 2024\n| girl a, smile\n| girl b, smile"
        )

    def test_parse_v3_payload_with_intent_and_continuity(self):
        text = (
            '{"version":3,"format":"single","intent":"selfie","continuity":"keep",'
            '"global":["selfie","looking at viewer","black pantyhose"],'
            '"people":[["smile"]]}'
        )
        payload = parse_structured_prompt_payload(text)
        self.assertIsNotNone(payload)
        self.assertEqual(payload.get("intent"), "selfie")
        self.assertEqual(payload.get("continuity"), "keep")
        self.assertEqual(
            parse_prompt_from_structured_output(text),
            "selfie, looking at viewer, black pantyhose, smile"
        )

    def test_parse_payload_from_json_with_noise(self):
        text = (
            'RESULT\n'
            '{"version":3,"format":"multi","intent":"normal","continuity":"switch",'
            '"global":["2girls","night"],"people":[["girl a"],["girl b"]]}'
            '\nEND'
        )
        payload = parse_structured_prompt_payload(text)
        self.assertIsNotNone(payload)
        self.assertEqual(payload.get("format"), "multi")
        self.assertEqual(payload.get("continuity"), "switch")


if __name__ == "__main__":
    unittest.main()
