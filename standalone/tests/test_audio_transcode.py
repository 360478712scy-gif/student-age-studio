"""Real audio conversions, content sniffing and bounded failure cleanup."""
import io
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audio_transcode as audio


class AudioBoundTests(unittest.TestCase):
    def test_rejects_empty_unsupported_and_oversize_input(self):
        for raw, extension in ((b'', '.wav'), (b'anything', '.mp4'), ('text', '.wav')):
            with self.assertRaises(ValueError):
                audio.convert(raw, extension)
        with patch.object(audio, 'MAX_INPUT', 1):
            with self.assertRaisesRegex(ValueError, '48 MB'):
                audio.convert(b'oversize', '.mp3')

    def test_concurrency_limit_does_not_wait(self):
        with patch.object(audio, '_slots', threading.BoundedSemaphore(0)):
            with self.assertRaisesRegex(ValueError, '稍后重试'):
                audio.convert(b'fixture', '.wav')

    def test_timeout_kills_and_reaps_process(self):
        process = Mock(returncode=None)
        process.poll.return_value = None
        with patch.object(audio.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(ValueError, '超时'):
                audio._run(['ffmpeg'], time.monotonic() - 1)
        process.kill.assert_called_once()
        process.wait.assert_called_once()

    def test_size_limit_kills_and_reaps_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'game.wav'
            output.write_bytes(b'oversize')
            process = Mock(returncode=None)
            process.poll.return_value = None
            with patch.object(audio.subprocess, 'Popen', return_value=process):
                with self.assertRaisesRegex(ValueError, '过大'):
                    audio._run(['ffmpeg'], time.monotonic() + 5, ((output, 2),))
            process.kill.assert_called_once()
            process.wait.assert_called_once()

    def test_failure_cleans_temporary_files_and_releases_slot(self):
        slots, recorded = threading.BoundedSemaphore(1), []
        temporary_directory = tempfile.TemporaryDirectory
        def temporary(**options):
            result = temporary_directory(**options)
            recorded.append(Path(result.name))
            return result
        with patch.object(audio, '_slots', slots), patch.object(audio, '_ffmpeg', return_value='ffmpeg'), \
                patch.object(audio.tempfile, 'TemporaryDirectory', side_effect=temporary), \
                patch.object(audio, '_run', side_effect=ValueError('decode failed')):
            with self.assertRaisesRegex(ValueError, 'decode failed'):
                audio.convert(b'fixture', '.mp3')
        self.assertTrue(slots.acquire(blocking=False))
        self.assertTrue(recorded)
        self.assertFalse(recorded[0].exists())

    def test_missing_component_has_audio_error(self):
        with patch.dict(sys.modules, {'imageio_ffmpeg': None}):
            with self.assertRaisesRegex(ValueError, '音频转换组件不可用'):
                audio.convert(b'fixture', '.mp3')

    def test_incomplete_wav_is_rejected(self):
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as output:
            output.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
            output.writeframes(b'\0' * 480)
        with self.assertRaisesRegex(ValueError, 'WAV 不完整'):
            audio._wav_metadata(stream.getvalue()[:-20])


class RealAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg = audio._ffmpeg()
            codecs = subprocess.run([cls.ffmpeg, '-hide_banner', '-encoders'],
                capture_output=True, text=True, check=True, timeout=10).stdout
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            raise unittest.SkipTest(f'Local bundled FFmpeg unavailable: {error}')
        for codec in ('aac', 'libmp3lame', 'libvorbis', 'flac'):
            if codec not in codecs:
                raise unittest.SkipTest(f'Local bundled FFmpeg lacks {codec}')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='studio-real-audio-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source.wav'
        self.run_ffmpeg(['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=0.15',
                         '-ac', '2', '-c:a', 'pcm_s16le', str(self.source)])

    def run_ffmpeg(self, options):
        return subprocess.run([self.ffmpeg, '-hide_banner', '-nostdin', '-v', 'error'] + options,
                              capture_output=True, check=True, timeout=15)

    def assert_result(self, raw, extension):
        result = audio.convert(raw, extension)
        self.assertEqual(result['audioCodec'], 'aac')
        self.assertEqual(result['profile'], 'LC')
        self.assertEqual(result['extension'], '.m4a')
        self.assertEqual(result['sampleRate'], 48000)
        self.assertEqual(result['channels'], 2)
        self.assertGreater(result['duration'], 0)
        self.assertEqual(result['size'], len(result['aac']))
        self.assertEqual(result['wavSize'], len(result['wav']))
        with wave.open(io.BytesIO(result['wav']), 'rb') as decoded:
            self.assertEqual(decoded.getparams()[:3], (2, 2, 48000))
            self.assertEqual(len(decoded.readframes(decoded.getnframes())), decoded.getnframes() * 4)
        output = self.root / 'checked.m4a'
        output.write_bytes(result['aac'])
        self.assertTrue(audio._fast_start(output))
        checked = subprocess.run([self.ffmpeg, '-hide_banner', '-nostdin', '-v', 'info',
            '-xerror', '-i', str(output), '-map', '0:a:0', '-f', 'null', '-'],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn('Audio: aac (LC)', checked.stderr)
        self.assertIn('48000 Hz, stereo', checked.stderr)
        return result

    def test_supported_formats_are_really_decoded_and_encoded(self):
        for extension, codec in (('.mp3', 'libmp3lame'), ('.wav', 'pcm_s16le'),
                                 ('.ogg', 'libvorbis'), ('.flac', 'flac'),
                                 ('.m4a', 'aac'), ('.aac', 'aac')):
            with self.subTest(extension=extension):
                source = self.root / ('input' + extension)
                self.run_ffmpeg(['-i', str(self.source), '-c:a', codec, str(source)])
                self.assert_result(source.read_bytes(), extension)

    def test_readable_m4a_with_mp3_extension_is_converted(self):
        source = self.root / 'actual.m4a'
        self.run_ffmpeg(['-i', str(self.source), '-c:a', 'aac', str(source)])
        result = self.assert_result(source.read_bytes(), '.mp3')
        self.assertEqual(result['inputCodec'], 'aac')

    def test_wav_uses_original_samples_without_lossy_aac_roundtrip(self):
        result = self.assert_result(self.source.read_bytes(), '.wav')
        with wave.open(str(self.source), 'rb') as original, wave.open(io.BytesIO(result['wav']), 'rb') as output:
            self.assertEqual(original.readframes(original.getnframes()), output.readframes(output.getnframes()))

    def test_corrupt_and_truncated_audio_are_rejected(self):
        for raw in (b'not audio', self.source.read_bytes()[:-200]):
            with self.assertRaises(ValueError):
                audio.convert(raw, '.wav')

    def test_video_without_audio_track_is_rejected(self):
        source = self.root / 'silent.mp4'
        self.run_ffmpeg(['-f', 'lavfi', '-i', 'testsrc=size=16x16:duration=0.1',
                         '-c:v', 'mpeg4', '-an', str(source)])
        with self.assertRaisesRegex(ValueError, '音轨'):
            audio.convert(source.read_bytes(), '.mp3')

    def test_output_bounds_clean_temporary_files(self):
        for bound in ('MAX_AAC', 'MAX_WAV'):
            with self.subTest(bound=bound), patch.object(audio, bound, 64):
                with self.assertRaisesRegex(ValueError, '过大'):
                    audio.convert(self.source.read_bytes(), '.wav')


if __name__ == '__main__':
    unittest.main()
