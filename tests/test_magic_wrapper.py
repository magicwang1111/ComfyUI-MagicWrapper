import asyncio
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

import torch


REPO_ROOT = Path(__file__).resolve().parents[1]
COMFY_ROOT = REPO_ROOT.parents[1]


def load_package():
    if str(COMFY_ROOT) not in sys.path:
        sys.path.insert(0, str(COMFY_ROOT))

    spec = spec_from_file_location(
        "magicwrapper",
        REPO_ROOT / "__init__.py",
        submodule_search_locations=[str(REPO_ROOT)],
    )
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_package()
MagicBatchToImageList = MODULE.NODE_CLASS_MAPPINGS["MagicBatchToImageList"]
MagicImageListToBatch = MODULE.NODE_CLASS_MAPPINGS["MagicImageListToBatch"]
MagicImageBatchConcat = MODULE.NODE_CLASS_MAPPINGS["MagicImageBatchConcat"]
MagicForEachImageStart = MODULE.NODE_CLASS_MAPPINGS["MagicForEachImageStart"]
MagicForEachImageEnd = MODULE.NODE_CLASS_MAPPINGS["MagicForEachImageEnd"]
MagicPromptSelect = MODULE.NODE_CLASS_MAPPINGS["MagicPromptSelect"]
MagicAudioSpeed = MODULE.NODE_CLASS_MAPPINGS["MagicAudioSpeed"]
PROMPT_LIBRARY = sys.modules["magicwrapper.mw_prompt_library"]


class FakeDynPrompt:
    def __init__(self, prompt):
        self._prompt = prompt

    def get_node(self, node_id):
        return self._prompt[node_id]

    def get_display_node_id(self, node_id):
        return node_id

    def get_original_prompt(self):
        return self._prompt


def make_image_batch(batch, height=4, width=4, channels=3):
    total = batch * height * width * channels
    values = torch.arange(total, dtype=torch.float32)
    return values.reshape(batch, height, width, channels)


def make_audio(samples=16000, sample_rate=16000, channels=1):
    timeline = torch.arange(samples, dtype=torch.float32) / sample_rate
    waveform = torch.sin(2 * torch.pi * 440.0 * timeline)
    waveform = waveform.reshape(1, 1, samples).repeat(1, channels, 1)
    return {"waveform": waveform, "sample_rate": sample_rate}


def write_prompts_file(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


class FakeRoutes:
    def __init__(self):
        self.handlers = {}

    def get(self, path):
        def decorator(func):
            self.handlers[path] = func
            return func

        return decorator


class MagicWrapperTests(unittest.TestCase):
    def swap_prompts_path(self, prompts_path):
        original = PROMPT_LIBRARY.PROMPTS_JSON_PATH
        PROMPT_LIBRARY.PROMPTS_JSON_PATH = Path(prompts_path)
        self.addCleanup(setattr, PROMPT_LIBRARY, "PROMPTS_JSON_PATH", original)

    def reset_prompt_route_registration(self):
        original = PROMPT_LIBRARY._PROMPT_ROUTES_REGISTERED
        PROMPT_LIBRARY._PROMPT_ROUTES_REGISTERED = False
        self.addCleanup(setattr, PROMPT_LIBRARY, "_PROMPT_ROUTES_REGISTERED", original)

    def test_batch_to_list_and_back_preserves_order(self):
        image = make_image_batch(3)
        split = MagicBatchToImageList().split(image)[0]

        self.assertEqual(len(split), 3)
        self.assertTrue(all(item.shape == (1, 4, 4, 3) for item in split))

        rebuilt = MagicImageListToBatch().combine(split)[0]
        self.assertTrue(torch.equal(rebuilt, image))

    def test_image_list_to_batch_rejects_mismatched_shapes(self):
        first = torch.zeros((1, 4, 4, 3), dtype=torch.float32)
        second = torch.zeros((1, 5, 4, 3), dtype=torch.float32)

        with self.assertRaisesRegex(ValueError, "shape"):
            MagicImageListToBatch().combine([first, second])

    def test_batch_concat_rejects_mismatched_shapes(self):
        first = torch.zeros((1, 4, 4, 3), dtype=torch.float32)
        second = torch.zeros((1, 4, 5, 3), dtype=torch.float32)

        with self.assertRaisesRegex(ValueError, "shape"):
            MagicImageBatchConcat().concat(first, second)

    def test_audio_speed_node_is_registered(self):
        self.assertIn("MagicAudioSpeed", MODULE.NODE_CLASS_MAPPINGS)
        self.assertEqual(
            MODULE.NODE_DISPLAY_NAME_MAPPINGS["MagicAudioSpeed"],
            "Magic Audio Speed",
        )

    def test_audio_speed_resample_changes_duration(self):
        audio = make_audio(samples=1000, sample_rate=1000, channels=2)

        result = MagicAudioSpeed().adjust(audio, speed=2.0, method="resample")[0]

        self.assertEqual(result["sample_rate"], 1000)
        self.assertEqual(result["waveform"].shape, (1, 2, 500))

    def test_audio_speed_preserve_pitch_changes_duration(self):
        audio = make_audio(samples=4096, sample_rate=16000)

        result = MagicAudioSpeed().adjust(audio, speed=1.25, method="preserve_pitch")[0]

        self.assertEqual(result["sample_rate"], 16000)
        self.assertEqual(result["waveform"].shape, (1, 1, 3277))

    def test_audio_speed_rejects_invalid_audio(self):
        with self.assertRaisesRegex(ValueError, "waveform"):
            MagicAudioSpeed().adjust({"sample_rate": 16000}, speed=1.0)

    def test_audio_speed_rejects_invalid_speed(self):
        audio = make_audio(samples=100)

        with self.assertRaisesRegex(ValueError, "speed"):
            MagicAudioSpeed().adjust(audio, speed=0.0)

    def test_for_each_start_returns_selected_image(self):
        images = make_image_batch(3)
        flow, index, total, image = MagicForEachImageStart().open_loop(images, initial_value0=1)

        self.assertEqual(flow, "stub")
        self.assertEqual(index, 1)
        self.assertEqual(total, 3)
        self.assertTrue(torch.equal(image, images[1:2]))

    def test_for_each_end_base_case_returns_processed_image(self):
        processed = torch.ones((1, 4, 4, 3), dtype=torch.float32)
        result = MagicForEachImageEnd().close_loop(
            flow=["start", 0],
            index=2,
            total=3,
            processed_image=processed,
            dynprompt=FakeDynPrompt({}),
            unique_id="end",
        )[0]

        self.assertTrue(torch.equal(result, processed))

    def test_for_each_end_recursive_case_expands_subgraph_and_advances_index(self):
        images = make_image_batch(3)
        processed = images[0:1].clone()
        dynprompt = FakeDynPrompt(
            {
                "start": {
                    "class_type": "MagicForEachImageStart",
                    "inputs": {"images": images},
                },
                "process": {
                    "class_type": "MockProcessor",
                    "inputs": {"image": ["start", 3]},
                },
                "end": {
                    "class_type": "MagicForEachImageEnd",
                    "inputs": {
                        "flow": ["start", 0],
                        "index": ["start", 1],
                        "total": ["start", 2],
                        "processed_image": ["process", 0],
                    },
                },
            }
        )

        result = MagicForEachImageEnd().close_loop(
            flow=["start", 0],
            index=0,
            total=3,
            processed_image=processed,
            dynprompt=dynprompt,
            unique_id="end",
        )

        self.assertIsInstance(result, dict)
        self.assertIn("expand", result)
        self.assertIn("result", result)

        expand = result["expand"]
        recurse_start_id = next(
            node_id for node_id, node in expand.items() if node["class_type"] == "MagicForEachImageStart"
        )
        recurse_end_id = next(
            node_id for node_id, node in expand.items() if node["class_type"] == "MagicForEachImageEnd"
        )
        concat_id = next(
            node_id for node_id, node in expand.items() if node["class_type"] == "MagicImageBatchConcat"
        )

        self.assertEqual(expand[recurse_start_id]["inputs"]["initial_value0"], 1)
        self.assertIs(expand[concat_id]["inputs"]["image_a"], processed)
        self.assertEqual(expand[concat_id]["inputs"]["image_b"], [recurse_end_id, 0])
        self.assertEqual(result["result"], ([concat_id, 0],))

    def test_prompt_name_choices_from_valid_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prompts_path = Path(temp_dir) / "prompts.json"
            write_prompts_file(
                prompts_path,
                [
                    {"name": "portrait_basic", "description": "portrait prompt"},
                    {"name": "product_photo", "description": "product prompt"},
                ],
            )

            choices = PROMPT_LIBRARY.get_prompt_name_choices(prompts_path)

        self.assertEqual(choices, ["portrait_basic", "product_photo"])

    def test_prompt_select_returns_matching_description(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prompts_path = Path(temp_dir) / "prompts.json"
            write_prompts_file(
                prompts_path,
                [
                    {"name": "portrait_basic", "description": "portrait prompt"},
                ],
            )
            self.swap_prompts_path(prompts_path)

            result = MagicPromptSelect().select_prompt("portrait_basic")[0]

        self.assertEqual(result, "portrait prompt")

    def test_prompt_loader_rejects_duplicate_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prompts_path = Path(temp_dir) / "prompts.json"
            write_prompts_file(
                prompts_path,
                [
                    {"name": "portrait_basic", "description": "first"},
                    {"name": "portrait_basic", "description": "second"},
                ],
            )

            with self.assertRaisesRegex(ValueError, "duplicate prompt name"):
                PROMPT_LIBRARY.load_prompt_items(prompts_path)

    def test_prompt_loader_rejects_missing_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prompts_path = Path(temp_dir) / "prompts.json"
            write_prompts_file(
                prompts_path,
                [
                    {"name": "portrait_basic"},
                ],
            )

            with self.assertRaisesRegex(ValueError, "non-empty string 'description'"):
                PROMPT_LIBRARY.load_prompt_items(prompts_path)

    def test_prompt_loader_rejects_empty_strings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prompts_path = Path(temp_dir) / "prompts.json"
            write_prompts_file(
                prompts_path,
                [
                    {"name": "  ", "description": "prompt"},
                ],
            )

            with self.assertRaisesRegex(ValueError, "non-empty string 'name'"):
                PROMPT_LIBRARY.load_prompt_items(prompts_path)

    def test_prompt_loader_rejects_invalid_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prompts_path = Path(temp_dir) / "prompts.json"
            prompts_path.write_text("{invalid", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                PROMPT_LIBRARY.load_prompt_items(prompts_path)

    def test_prompt_select_placeholder_raises_when_json_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prompts_path = Path(temp_dir) / "prompts.json"
            write_prompts_file(prompts_path, [])
            self.swap_prompts_path(prompts_path)

            choices = MagicPromptSelect.INPUT_TYPES()["required"]["prompt_name"][0]
            self.assertEqual(choices, [PROMPT_LIBRARY.PROMPTS_PLACEHOLDER])

            with self.assertRaisesRegex(ValueError, "no prompts are configured"):
                MagicPromptSelect().select_prompt(PROMPT_LIBRARY.PROMPTS_PLACEHOLDER)

    def test_register_prompt_routes_returns_false_without_instance(self):
        class FakePromptServer:
            instance = None

        self.reset_prompt_route_registration()

        registered = PROMPT_LIBRARY.register_prompt_routes(prompt_server_cls=FakePromptServer)

        self.assertFalse(registered)

    def test_prompt_route_returns_items(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prompts_path = Path(temp_dir) / "prompts.json"
            write_prompts_file(
                prompts_path,
                [
                    {"name": "portrait_basic", "description": "portrait prompt"},
                ],
            )

            routes = FakeRoutes()
            fake_server = type("FakePromptServer", (), {"instance": SimpleNamespace(routes=routes)})
            self.reset_prompt_route_registration()

            registered = PROMPT_LIBRARY.register_prompt_routes(
                prompt_server_cls=fake_server,
                prompts_path=prompts_path,
            )

            self.assertTrue(registered)
            handler = routes.handlers[PROMPT_LIBRARY.PROMPTS_ROUTE_PATH]
            response = asyncio.run(handler(None))

        self.assertEqual(response.status, 200)
        self.assertEqual(
            json.loads(response.text),
            {"items": [{"name": "portrait_basic", "description": "portrait prompt"}]},
        )

    def test_prompt_route_returns_error_for_invalid_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prompts_path = Path(temp_dir) / "prompts.json"
            prompts_path.write_text("{invalid", encoding="utf-8")

            routes = FakeRoutes()
            fake_server = type("FakePromptServer", (), {"instance": SimpleNamespace(routes=routes)})
            self.reset_prompt_route_registration()
            PROMPT_LIBRARY.register_prompt_routes(
                prompt_server_cls=fake_server,
                prompts_path=prompts_path,
            )

            handler = routes.handlers[PROMPT_LIBRARY.PROMPTS_ROUTE_PATH]
            response = asyncio.run(handler(None))

        self.assertEqual(response.status, 500)
        self.assertIn("invalid JSON", json.loads(response.text)["error"])


if __name__ == "__main__":
    unittest.main()
