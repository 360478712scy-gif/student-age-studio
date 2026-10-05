"""Create editor AAC and game PCM WAV directly from the same audio input."""
import io
import re
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

from platform_support import process_options
from video_transcode import _fast_start

EXTENSIONS = {'.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac'}
MAX_INPUT = 48 * 1024 * 1024
MAX_AAC = 64 * 1024 * 1024
MAX_WAV = 128 * 1024 * 1024
MAX_SECONDS = 45
_slots = threading.BoundedSemaphore(2)
_CORRUPTION = re.compile(r'^\[[^\n]+\][^\n]*(?:File ended prematurely|Packet corrupt|'
                         r'corrupt input packet|partial file)', re.M | re.I)


def _ffmpeg():
    try:
        import imageio_ffmpeg
        executable = imageio_ffmpeg.get_ffmpeg_exe()
        if not Path(executable).is_file():
            raise OSError('FFmpeg is missing')
        return executable
    except (ImportError, OSError, RuntimeError) as error:
        raise ValueError('音频转换组件不可用，请重新安装完整客户端。') from error


def _check_sizes(outputs):
    for path, limit in outputs:
        if path.exists() and path.stat().st_size > limit:
            raise ValueError('转换后的音频过大（AAC 上限 64 MB、WAV 上限 128 MB），请剪短后重试。')


def _run(command, deadline, outputs=()):
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=errors, **process_options())
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise ValueError('音频转换超时，请剪短后重试。')
                _check_sizes(outputs)
                if errors.tell() > 1024 * 1024:
                    raise ValueError('音频解码异常，请使用完整、未损坏的音频。')
                time.sleep(.05)
            _check_sizes(outputs)
            errors.seek(0)
            log = errors.read(1024 * 1024).decode('utf-8', errors='replace')
            if process.returncode or _CORRUPTION.search(log):
                if 'Unknown encoder' in log or 'Encoder not found' in log:
                    raise ValueError('音频转换组件不支持 AAC，请重新安装完整客户端。')
                raise ValueError('无法解码这个音频，请使用包含音轨的完整、未损坏文件。')
            return log
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def _wav_metadata(raw):
    try:
        with wave.open(io.BytesIO(raw), 'rb') as decoded:
            channels, rate, frames = decoded.getnchannels(), decoded.getframerate(), decoded.getnframes()
            if channels != 2 or rate != 48000 or decoded.getsampwidth() != 2 or frames <= 0:
                raise ValueError('Invalid PCM output')
            remaining = frames * channels * 2
            while remaining:
                chunk = decoded.readframes(min(8192, remaining // (channels * 2)))
                if not chunk:
                    raise ValueError('Incomplete PCM output')
                remaining -= len(chunk)
            return {'duration': frames / rate, 'sampleRate': rate, 'channels': channels,
                    'wavCodec': 'pcm_s16le', 'wavFrames': frames}
    except (wave.Error, EOFError, ValueError) as error:
        raise ValueError('转换后的 WAV 不完整或无法读取，请重试。') from error


def convert(raw, extension):
    """Return {'aac': M4A bytes, 'wav': PCM16 bytes, ...real metadata}.

    The extension limits the import UI's supported choices. FFmpeg sniffs actual
    contents, so a playable M4A renamed MP3 is converted instead of relabelled.
    The caller must release editor/store locks before this bounded operation.
    """
    if not isinstance(extension, str) or extension.lower() not in EXTENSIONS:
        raise ValueError('音频格式不支持，请选择 MP3、WAV、OGG、FLAC、M4A 或 AAC。')
    if not isinstance(raw, (bytes, bytearray, memoryview)) or not 0 < len(raw) <= MAX_INPUT:
        raise ValueError('上传音频为空或超过 48 MB。')
    if not _slots.acquire(blocking=False):
        raise ValueError('已有音频正在转换，请稍后重试。')
    try:
        ffmpeg = _ffmpeg()
        deadline = time.monotonic() + MAX_SECONDS
        with tempfile.TemporaryDirectory(prefix='studio-audio-') as temporary:
            root = Path(temporary)
            source, aac, wav = root / ('source' + extension.lower()), root / 'editor.m4a', root / 'game.wav'
            source.write_bytes(raw)
            base = [ffmpeg, '-hide_banner', '-nostdin', '-nostats', '-v', 'info',
                    '-xerror', '-err_detect', 'explode', '-protocol_whitelist', 'file,pipe']
            outputs = ((aac, MAX_AAC), (wav, MAX_WAV))
            # Both encoders receive decoded original samples in this one process.
            log = _run(base + ['-i', str(source), '-map', '0:a:0', '-vn',
                              '-c:a', 'aac', '-profile:a', 'aac_low', '-b:a', '192k',
                              '-ac', '2', '-ar', '48000', '-movflags', '+faststart',
                              '-f', 'ipod', str(aac), '-map', '0:a:0', '-vn',
                              '-c:a', 'pcm_s16le', '-ac', '2', '-ar', '48000',
                              '-f', 'wav', str(wav)], deadline, outputs)
            input_audio = re.search(r'Audio: ([^,\n]+)', log.split('Output #', 1)[0])
            if not input_audio or not aac.is_file() or not wav.is_file():
                raise ValueError('文件没有可读取的音轨，请选择音频文件。')
            # Fully decode the AAC file; reading WAV with wave also validates PCM length.
            checked = _run(base + ['-i', str(aac), '-map', '0:a:0', '-vn',
                                    '-f', 'null', '-'], deadline, outputs)
            description = checked.split('Output #', 1)[0]
            if (not re.search(r'Audio: aac \(LC\)(?: \([^,\n]+\))?, 48000 Hz, stereo,', description)
                    or not _fast_start(aac)):
                raise ValueError('音频转换结果不兼容，请重试。')
            aac_raw, wav_raw = aac.read_bytes(), wav.read_bytes()
            metadata = _wav_metadata(wav_raw)
            return {'aac': aac_raw, 'wav': wav_raw, **metadata, 'container': 'm4a',
                    'extension': '.m4a', 'mime': 'audio/mp4', 'audioCodec': 'aac',
                    'profile': 'LC', 'fastStart': True, 'size': len(aac_raw),
                    'wavSize': len(wav_raw), 'inputCodec': input_audio.group(1).split()[0]}
    except OSError as error:
        raise ValueError('音频转换组件无法运行或文件无法写入，请检查安装和磁盘空间。') from error
    finally:
        _slots.release()
