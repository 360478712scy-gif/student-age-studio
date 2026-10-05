"""Actual codec/decode regressions plus bounded-process failure cases."""
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import video_transcode as video


class VideoBoundTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='studio-video-tests-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.destination = self.root / 'source.webm', self.root / 'result.mp4'
        self.source.write_bytes(b'fixture')
        self.destination.write_bytes(b'existing destination')

    def test_input_extension_empty_and_size_bounds(self):
        for source in (self.root / 'image.png', self.root / 'empty.mp4'):
            source.write_bytes(b'')
            with self.assertRaises(ValueError):
                video.transcode(source, self.destination)
        with patch.object(video, 'MAX_INPUT', 3):
            with self.assertRaisesRegex(ValueError, '256 MB'):
                video.transcode(self.source, self.destination)
        self.assertEqual(self.destination.read_bytes(), b'existing destination')

    def test_same_path_never_overwrites_source(self):
        with self.assertRaisesRegex(ValueError, '独立'):
            video.transcode(self.source, self.source)
        self.assertEqual(self.source.read_bytes(), b'fixture')

    def test_concurrent_conversion_limit_fails_without_waiting(self):
        with patch.object(video, '_slots', threading.BoundedSemaphore(0)):
            with self.assertRaisesRegex(ValueError, '稍后重试'):
                video.transcode(self.source, self.destination)

    def test_timeout_kills_and_reaps_child(self):
        process = Mock(returncode=None)
        process.poll.return_value = None
        with patch.object(video.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(ValueError, '超时'):
                video._run(['ffmpeg'], time.monotonic() - 1)
        process.kill.assert_called_once()
        process.wait.assert_called_once()

    def test_output_size_kills_and_reaps_child(self):
        process = Mock(returncode=None)
        process.poll.return_value = None
        with patch.object(video, 'MAX_OUTPUT', 2), patch.object(video.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(ValueError, '512 MB'):
                video._run(['ffmpeg'], time.monotonic() + 5, self.destination)
        process.kill.assert_called_once()
        process.wait.assert_called_once()

    def test_failed_conversion_preserves_destination_and_releases_slot(self):
        slots = threading.BoundedSemaphore(1)
        with patch.object(video, '_slots', slots), patch.object(video, '_ffmpeg', return_value='ffmpeg'), \
                patch.object(video, '_run', side_effect=ValueError('decode failed')):
            with self.assertRaisesRegex(ValueError, 'decode failed'):
                video.transcode(self.source, self.destination)
        self.assertTrue(slots.acquire(blocking=False))
        self.assertEqual(self.destination.read_bytes(), b'existing destination')
        self.assertEqual(list(self.root.glob('studio-video-*')), [])

    def test_missing_component_has_clear_error(self):
        with patch.object(video, '_ffmpeg', side_effect=ValueError('视频转换组件不可用')):
            with self.assertRaisesRegex(ValueError, '组件不可用'):
                video.transcode(self.source, self.destination)

    def test_fast_start_checks_box_order_and_truncated_structure(self):
        box = lambda kind: struct.pack('>I4s', 8, kind)
        self.destination.write_bytes(box(b'ftyp') + box(b'moov') + box(b'mdat'))
        self.assertTrue(video._fast_start(self.destination))
        self.destination.write_bytes(box(b'ftyp') + box(b'mdat') + box(b'moov'))
        self.assertFalse(video._fast_start(self.destination))
        self.destination.write_bytes(struct.pack('>I4s', 100, b'moov'))
        self.assertFalse(video._fast_start(self.destination))


class RealVideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg = video._ffmpeg()
            codecs = subprocess.run([cls.ffmpeg, '-hide_banner', '-encoders'],
                capture_output=True, text=True, check=True, timeout=10).stdout
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            raise unittest.SkipTest(f'Local bundled FFmpeg unavailable: {error}')
        for codec in ('libx264', 'libvpx', 'libvorbis', 'aac'):
            if codec not in codecs:
                raise unittest.SkipTest(f'Local bundled FFmpeg lacks {codec}')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='studio-real-video-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.destination = self.root / 'source.webm', self.root / 'result.mp4'

    def make_video(self, audio=False, width=64, height=48):
        command = [self.ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-f', 'lavfi',
                   '-i', f'testsrc=size={width}x{height}:rate=10:duration=0.4']
        if audio:
            command += ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100:duration=0.4']
        command += ['-c:v', 'libvpx', '-pix_fmt', 'yuv420p']
        command += ['-c:a', 'libvorbis', '-shortest'] if audio else ['-an']
        subprocess.run(command + [str(self.source)], check=True, capture_output=True, timeout=15)

    def assert_result(self, has_audio, width=64, height=48):
        result = video.transcode(self.source, self.destination)
        self.assertEqual(result['container'], 'mp4')
        self.assertEqual(result['videoCodec'], 'h264')
        self.assertEqual(result['pixelFormat'], 'yuv420p')
        self.assertEqual(result['audioCodec'], 'aac' if has_audio else None)
        self.assertEqual(result['hasAudio'], has_audio)
        self.assertEqual((result['width'], result['height']), (width, height))
        self.assertEqual(result['frames'], 4)
        self.assertGreater(result['duration'], 0)
        self.assertEqual(result['size'], self.destination.stat().st_size)
        self.assertTrue(video._fast_start(self.destination))
        # Independent FFmpeg invocation verifies the promoted file is fully decodable.
        checked = subprocess.run([self.ffmpeg, '-hide_banner', '-nostdin', '-v', 'info',
            '-xerror', '-i', str(self.destination), '-map', '0:v:0', '-map', '0:a:0?',
            '-f', 'null', '-'], capture_output=True, text=True, timeout=15)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn('Video: h264', checked.stderr)
        self.assertIn('yuv420p', checked.stderr)
        if has_audio:
            self.assertIn('Audio: aac', checked.stderr)
            self.assertIn('48000 Hz, stereo', checked.stderr)

    def test_vp8_vorbis_webm_becomes_h264_aac_fast_start_mp4(self):
        self.make_video(audio=True)
        self.assert_result(has_audio=True)

    def test_silent_webm_keeps_no_audio_track(self):
        self.make_video()
        self.assert_result(has_audio=False)

    def test_odd_dimensions_are_padded_to_even(self):
        self.make_video(width=65, height=49)
        self.assert_result(has_audio=False, width=66, height=50)

    def test_audio_only_container_is_rejected(self):
        subprocess.run([self.ffmpeg, '-hide_banner', '-nostdin', '-v', 'error',
            '-f', 'lavfi', '-i', 'sine=duration=0.1', '-c:a', 'libvorbis', str(self.source)],
            check=True, capture_output=True, timeout=15)
        with self.assertRaises(ValueError):
            video.transcode(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_renamed_picture_is_rejected(self):
        source = self.root / 'picture.png'
        subprocess.run([self.ffmpeg, '-hide_banner', '-nostdin', '-v', 'error',
            '-f', 'lavfi', '-i', 'testsrc=size=32x32', '-frames:v', '1', str(source)],
            check=True, capture_output=True, timeout=15)
        source.rename(self.source)
        with self.assertRaisesRegex(ValueError, '视频画面'):
            video.transcode(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_corrupt_input_is_rejected(self):
        self.source.write_bytes(b'not a video')
        with self.assertRaises(ValueError):
            video.transcode(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_truncated_webm_is_rejected_even_when_ffmpeg_exits_zero(self):
        self.make_video()
        raw = self.source.read_bytes()
        self.source.write_bytes(raw[:-len(raw) // 3])
        with self.assertRaises(ValueError):
            video.transcode(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_failure_after_encoding_removes_partial_output(self):
        self.make_video()
        self.destination.write_bytes(b'keep original')
        with patch.object(video, '_fast_start', return_value=False):
            with self.assertRaisesRegex(ValueError, '不兼容'):
                video.transcode(self.source, self.destination)
        self.assertEqual(self.destination.read_bytes(), b'keep original')
        self.assertEqual(list(self.root.glob('studio-video-*')), [])

    def test_output_size_bound_cleans_partial_output(self):
        self.make_video()
        with patch.object(video, 'MAX_OUTPUT', 128):
            with self.assertRaisesRegex(ValueError, '512 MB'):
                video.transcode(self.source, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.glob('studio-video-*')), [])


if __name__ == '__main__':
    unittest.main()
