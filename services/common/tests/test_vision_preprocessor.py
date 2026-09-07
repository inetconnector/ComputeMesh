"""Unit tests for ComputeMesh Vision Preprocessor."""
from __future__ import annotations

import base64
import io
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image
from services.common.vision_preprocessor import (
    ProcessedImage,
    VisionPreprocessingError,
    VisionPreprocessor,
    get_vision_preprocessor,
)


class TestVisionPreprocessor(unittest.TestCase):
    def setUp(self) -> None:
        self.preprocessor = VisionPreprocessor(max_edge=1344, min_edge=28)

    def _create_sample_image_bytes(
        self,
        width: int,
        height: int,
        fmt: str = "PNG",
        mode: str = "RGB",
        color: tuple = (120, 150, 200),
    ) -> bytes:
        img = Image.new(mode, (width, height), color)
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        return buf.getvalue()

    def test_singleton_accessor(self) -> None:
        p1 = get_vision_preprocessor()
        p2 = get_vision_preprocessor()
        self.assertIs(p1, p2)
        self.assertIsInstance(p1, VisionPreprocessor)

    def test_process_normal_image(self) -> None:
        raw = self._create_sample_image_bytes(800, 600, fmt="JPEG")
        result = self.preprocessor.process_image(raw)
        self.assertIsInstance(result, ProcessedImage)
        self.assertEqual(result.width, 800)
        self.assertEqual(result.height, 600)
        self.assertEqual(result.original_width, 800)
        self.assertEqual(result.original_height, 600)
        self.assertEqual(result.mime_type, "image/jpeg")
        self.assertTrue(result.data_base64)
        self.assertTrue(result.data_uri.startswith("data:image/jpeg;base64,"))
        self.assertGreater(result.estimated_tokens, 0)
        self.assertAlmostEqual(result.aspect_ratio, 800 / 600, places=3)

    def test_downscale_large_image_preserves_aspect_ratio(self) -> None:
        # Large image 4000 x 2000 (aspect 2:1) -> max_edge 1344 -> 1344 x 672
        raw = self._create_sample_image_bytes(4000, 2000, fmt="PNG")
        result = self.preprocessor.process_image(raw, max_edge=1344)
        self.assertEqual(result.original_width, 4000)
        self.assertEqual(result.original_height, 2000)
        self.assertEqual(result.width, 1344)
        self.assertEqual(result.height, 672)
        self.assertLessEqual(result.width, 1344)
        self.assertLessEqual(result.height, 1344)
        self.assertAlmostEqual(result.aspect_ratio, 2.0, places=2)

    def test_upscale_sub_minimal_image(self) -> None:
        # Very small image 10 x 5 -> min_edge 28 -> scale 2.8 -> 28 x 14
        raw = self._create_sample_image_bytes(10, 5, fmt="PNG")
        result = self.preprocessor.process_image(raw, min_edge=28)
        self.assertEqual(result.original_width, 10)
        self.assertEqual(result.original_height, 5)
        self.assertGreaterEqual(result.width, 28)
        self.assertGreaterEqual(result.height, 14)

    def test_rgba_transparency_converted_to_rgb(self) -> None:
        # RGBA image with alpha channel
        img = Image.new("RGBA", (100, 100), (255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = self.preprocessor.process_image(buf.getvalue())
        self.assertEqual(result.mime_type, "image/jpeg")
        # Ensure processed output opens as RGB
        decoded = base64.b64decode(result.data_base64)
        out_img = Image.open(io.BytesIO(decoded))
        self.assertEqual(out_img.mode, "RGB")

    def test_data_uri_input(self) -> None:
        raw = self._create_sample_image_bytes(200, 200, fmt="PNG")
        b64 = base64.b64encode(raw).decode("ascii")
        data_uri = f"data:image/png;base64,{b64}"
        result = self.preprocessor.process_image(data_uri)
        self.assertEqual(result.original_width, 200)
        self.assertEqual(result.original_height, 200)
        self.assertEqual(result.width, 200)
        self.assertEqual(result.height, 200)

    def test_raw_base64_string_input(self) -> None:
        raw = self._create_sample_image_bytes(300, 150, fmt="JPEG")
        b64 = base64.b64encode(raw).decode("ascii")
        result = self.preprocessor.process_image(b64)
        self.assertEqual(result.original_width, 300)
        self.assertEqual(result.original_height, 150)

    def test_invalid_input_handling(self) -> None:
        with self.assertRaises(VisionPreprocessingError):
            self.preprocessor.process_image("")

        with self.assertRaises(VisionPreprocessingError):
            self.preprocessor.process_image("data:image/jpeg;base64,invalid-base64-content!!")

        with self.assertRaises(VisionPreprocessingError):
            self.preprocessor.process_image(b"not-an-image-header-garbage")

    def test_extract_openai_multimodal_content(self) -> None:
        raw1 = self._create_sample_image_bytes(400, 300, fmt="JPEG")
        b64_1 = base64.b64encode(raw1).decode("ascii")
        data_uri = f"data:image/jpeg;base64,{b64_1}"

        content_list = [
            {"type": "text", "text": "Analyze this diagram:"},
            {"type": "image_url", "image_url": {"url": data_uri}},
            {"type": "text", "text": "What components are shown?"},
        ]

        text, images = self.preprocessor.extract_and_preprocess_multimodal_content(content_list)
        self.assertEqual(text, "Analyze this diagram: What components are shown?")
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].original_width, 400)
        self.assertEqual(images[0].original_height, 300)

    def test_normalize_multimodal_messages(self) -> None:
        raw = self._create_sample_image_bytes(560, 280, fmt="PNG")
        b64 = base64.b64encode(raw).decode("ascii")

        messages = [
            {"role": "system", "content": "You are a professional Vision AI expert."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image in detail."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            },
        ]

        norm_msgs, total_tokens = self.preprocessor.normalize_multimodal_messages(messages)
        self.assertEqual(len(norm_msgs), 2)
        self.assertEqual(norm_msgs[0]["role"], "system")
        self.assertEqual(norm_msgs[0]["content"], "You are a professional Vision AI expert.")
        self.assertNotIn("images", norm_msgs[0])

        self.assertEqual(norm_msgs[1]["role"], "user")
        self.assertEqual(norm_msgs[1]["content"], "Describe this image in detail.")
        self.assertIn("images", norm_msgs[1])
        self.assertEqual(len(norm_msgs[1]["images"]), 1)
        # Vision tokens should be estimated and added to total_tokens
        self.assertGreater(total_tokens, 200)

    def test_ollama_multimodal_normalization(self) -> None:
        raw = self._create_sample_image_bytes(280, 280, fmt="JPEG")
        b64 = base64.b64encode(raw).decode("ascii")

        messages = [
            {
                "role": "user",
                "content": "What is in this picture?",
                "images": [b64],
            }
        ]

        norm_msgs, total_tokens = self.preprocessor.normalize_multimodal_messages(messages)
        self.assertEqual(len(norm_msgs), 1)
        self.assertEqual(norm_msgs[0]["content"], "What is in this picture?")
        self.assertEqual(len(norm_msgs[0]["images"]), 1)
        self.assertGreater(total_tokens, 100)


if __name__ == "__main__":
    unittest.main()
