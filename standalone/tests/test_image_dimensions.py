"""Generated images only; no game or Mod assets copied."""
import io
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from PIL import Image

class ImageDimensions(unittest.TestCase):
    def test_large_images_keep_dimensions_and_transparency(self):
        for size in [(5000, 32), (32, 5000), (4200, 4200)]:
            with self.subTest(size=size):
                raw = io.BytesIO()
                with Image.new('RGBA', size, (20, 40, 60, 128)) as image:
                    image.save(raw, format='PNG')
                result, extension, width, height = server.normalize_image(raw.getvalue())
                self.assertEqual((width, height), size)
                self.assertEqual(extension, '.png')
                with Image.open(io.BytesIO(result)) as image:
                    self.assertEqual(image.size, size)
                    self.assertEqual(image.getpixel((0, 0)), (20, 40, 60, 128))

    def test_invalid_image_still_reports_decode_error(self):
        with self.assertRaises(server.ApiError):
            server.normalize_image(b'not an image')
