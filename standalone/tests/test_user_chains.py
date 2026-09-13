"""User-chain regression tests: import image/audio, portrait preview, scan, save.

Mirrors real user flows without game files or GUI. All assertions target
observable behavior (accept/reject sets, output bytes, found sets), never
internal timings, so perf-only refactors must keep them green.
"""
import base64
import hashlib
import io
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image


class _StubBackend:
    """Minimal backend for AssetCatalog._validate_file (real PIL, real errors)."""

    def __init__(self, settings_file):
        self._settings_file = Path(settings_file)
        self.Image = Image

    class ApiError(Exception):
        def __init__(self, message, status=400, code="invalid_request"):
            super().__init__(message)
            self.message, self.status, self.code = message, status, code

    def settings_path(self):
        return self._settings_file

    @staticmethod
    def inside(path, root):
        try:
            Path(path).resolve().relative_to(Path(root).resolve())
            return True
        except (ValueError, OSError):
            return False


def _make_catalog(tmp):
    import asset_catalog

    backend = _StubBackend(tmp / "asset-folders.json")
    return asset_catalog.AssetCatalog(store=None, backend=backend, settings_path=tmp / "asset-folders.json")


class ImageImportChainTest(unittest.TestCase):
    """User: picks an image in the asset picker -> validates -> imports."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "mods").mkdir()
        self.env = patch.dict(os.environ, {"STUDIO_CACHE_ROOT": str(self.root / "Cache")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.catalog = _make_catalog(self.root)

    def _write(self, name, mode="RGB", size=(300, 200), color=(10, 200, 90), fmt="PNG"):
        from server import ApiError  # noqa: ensure server importable in chain env

        path = self.root / "mods" / name
        Image.new(mode, size, color).save(path, format=fmt)
        return path

    def test_rgb_import_keeps_dimensions(self):
        import server

        path = self._write("bg.png")
        info = self.catalog._validate_file(path, "background", self.root / "mods")
        self.assertEqual((info["width"], info["height"]), (300, 200))
        out, ext, width, height = server.normalize_image(path.read_bytes())
        self.assertEqual(ext, ".png")
        self.assertEqual((width, height), (300, 200))
        with Image.open(io.BytesIO(out)) as decoded:
            decoded.load()
            self.assertEqual(decoded.size, (300, 200))

    def test_rgba_import_keeps_alpha(self):
        import server

        path = self._write("role.png", mode="RGBA", size=(64, 48), color=(10, 200, 90, 128))
        out, ext, width, height = server.normalize_image(path.read_bytes())
        with Image.open(io.BytesIO(out)) as decoded:
            decoded.load()
            self.assertIn("A", decoded.getbands())
            self.assertEqual(decoded.size, (64, 48))

    def test_corrupt_image_rejected_same_as_before(self):
        import server

        bad = self.root / "mods" / "bad.png"
        bad.write_bytes(b"not an image at all")
        with self.assertRaises(Exception):
            self.catalog._validate_file(bad, "background", self.root / "mods")
        with self.assertRaises(server.ApiError):
            server.normalize_image(bad.read_bytes())

    def test_validation_lru_recomputes_identically(self):
        self.catalog._validation_cap = 3
        paths = [self._write(f"v{i}.png", size=(16 + i, 16)) for i in range(4)]
        first = self.catalog._validate_file(paths[0], "background", self.root / "mods")
        for path in paths[1:]:
            self.catalog._validate_file(path, "background", self.root / "mods")
        self.assertEqual(len(self.catalog.validation), 3)
        again = self.catalog._validate_file(paths[0], "background", self.root / "mods")
        self.assertEqual(first, again)


class AudioImportChainTest(unittest.TestCase):
    """User: uploads a WAV -> validated -> duplicate detection by digest."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def _wav_bytes(self, frames=8000, trunc=False):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x01\x02" * frames)
        data = buf.getvalue()
        return data[:-100] if trunc else data

    def test_valid_wav_accepted(self):
        import server

        payload = {"fileName": "voice.wav", "data": base64.b64encode(self._wav_bytes()).decode()}
        raw, ext = server.decode_audio(payload)
        self.assertEqual(ext, ".wav")
        self.assertTrue(len(raw) > 0)

    def test_truncated_wav_rejected(self):
        import server

        payload = {"fileName": "voice.wav", "data": base64.b64encode(self._wav_bytes(trunc=True)).decode()}
        with self.assertRaises(server.ApiError):
            server.decode_audio(payload)

    def test_chunked_file_hash_matches_oneshot(self):
        blob = b"abcd" * 300000
        target = self.root / "sfx.wav"
        target.write_bytes(blob)
        digest = hashlib.sha256()
        with target.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        self.assertEqual(digest.hexdigest(), hashlib.sha256(blob).hexdigest())


class PortraitPreviewChainTest(unittest.TestCase):
    """User: opens a character -> expression preview renders deterministically."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def _texture(self, name):
        img = Image.new("RGBA", (128, 128))
        px = img.load()
        for y in range(128):
            for x in range(128):
                px[x, y] = (x * 2 % 256, y * 2 % 256, (x + y) % 256, 255)
        path = self.root / name
        img.save(path)
        return str(path)

    def test_lazy_texture_subset_and_deterministic_png(self):
        from portrait_raster import Raster

        tex0, tex1 = self._texture("t0.png"), self._texture("t1.png")
        raster = Raster([tex0, tex1], [0, 0, 8, 8], 300, 300)
        row = {"indices": [0, 1, 2], "texture": 1,
               "vertices": [[0, 0, 0, 0], [8, 0, 1, 0], [0, 8, 0, 1]],
               "visible": True, "opacity": 1.0, "masks": [], "order": 0,
               "multiply": [1, 1, 1, 1], "screen": [0, 0, 0, 0], "flags": 0}
        box, pixels = raster.mesh(row)
        self.assertEqual(tuple(int(v) for v in box), (0, 0, 300, 300))
        self.assertGreater(float(pixels.sum()), 0)
        # Only the used texture was decoded.
        self.assertEqual(sorted(raster._textures.keys()), [1])
        out1, out2 = self.root / "r1.png", self.root / "r2.png"
        raster.render([row], str(out1))
        raster.render([row], str(out2))
        self.assertEqual(out1.read_bytes(), out2.read_bytes())


class BackgroundScanChainTest(unittest.TestCase):
    """User: puts files in folders -> background scan finds them, skips system dirs."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_scan_finds_media_and_skips_backups(self):
        from media_warmup import MediaWarmup

        root = self.root / "assets"
        (root / "sub").mkdir(parents=True)
        (root / "Backups").mkdir(parents=True)
        (root / "node_modules").mkdir(parents=True)
        (root / "a.png").write_bytes(b"\x89PNG" + b"0" * 64)
        (root / "sub" / "b.jpg").write_bytes(b"\xff\xd8" + b"1" * 64)
        (root / "Backups" / "c.png").write_bytes(b"\x89PNG" + b"2" * 64)
        (root / "node_modules" / "d.png").write_bytes(b"\x89PNG" + b"3" * 64)
        (root / "note.txt").write_text("not media")

        warmer = MediaWarmup.__new__(MediaWarmup)

        class _Stop:
            def is_set(self):
                return False

        warmer.stop = _Stop()
        found = warmer.files([root], set())
        names = sorted(Path(k).name for k in found)
        self.assertIn("a.png", names)
        self.assertIn("b.jpg", names)
        self.assertNotIn("c.png", names)
        self.assertNotIn("d.png", names)
        self.assertNotIn("note.txt", names)

        excluded = warmer.files([root], {(root / "sub").resolve()})
        self.assertNotIn("b.jpg", [Path(k).name for k in excluded])


class SaveFingerprintChainTest(unittest.TestCase):
    """User: saves a mod -> fingerprint stable; atomic writes round-trip."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_fingerprint_stable_and_dir_tuple(self):
        from platform_support import file_fingerprint

        target = self.root / "doc.txt"
        target.write_bytes(b"x" * 1000)
        first = file_fingerprint(target)
        self.assertEqual(len(first), 7)
        self.assertEqual(first, file_fingerprint(target))
        as_dir = file_fingerprint(self.root)
        self.assertEqual(len(as_dir), 7)

    def test_atomic_write_roundtrip_both_modes(self):
        from server import atomic_write

        data = b'{"hello": "world"}'
        plain, nofsync = self.root / "a.json", self.root / "b.json"
        atomic_write(plain, data)
        atomic_write(nofsync, data, fsync=False)
        self.assertEqual(plain.read_bytes(), data)
        self.assertEqual(nofsync.read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
