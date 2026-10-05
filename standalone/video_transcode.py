"""Bounded local video conversion for Unity-compatible MP4 imports."""
import math
import re
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from platform_support import process_options, replace_file

EXTENSIONS = {'.mp4', '.webm', '.mov', '.mkv', '.avi', '.m4v', '.mpeg', '.mpg'}
MAX_INPUT = 256 * 1024 * 1024
MAX_OUTPUT = 512 * 1024 * 1024
MAX_SECONDS = 120
_slots = threading.BoundedSemaphore(2)
_CONTAINERS = {'mov', 'mp4', 'matroska', 'webm', 'avi', 'mpeg', 'mpegvideo'}
_CORRUPTION = re.compile(r'^\[[^\n]+\][^\n]*(?:File ended prematurely|Packet corrupt|'
                         r'corrupt input packet|Invalid NAL unit|partial file)', re.M | re.I)


def _ffmpeg():
    try:
        import imageio_ffmpeg
        executable = imageio_ffmpeg.get_ffmpeg_exe()
        if not Path(executable).is_file():
            raise OSError('FFmpeg is missing')
        return executable
    except (ImportError, OSError, RuntimeError) as error:
        raise ValueError('视频转换组件不可用，请重新安装完整客户端。') from error


def _run(command, deadline, output=None):
    # Files keep FFmpeg logs from blocking a pipe or growing in Python memory.
    with tempfile.TemporaryFile() as progress, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=progress,
                                   stderr=errors, **process_options())
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise ValueError('视频转换超时，请剪短视频后重试。')
                if output is not None and output.exists() and output.stat().st_size > MAX_OUTPUT:
                    raise ValueError('转换后的视频超过 512 MB，请剪短或缩小视频。')
                if errors.tell() > 1024 * 1024 or progress.tell() > 1024 * 1024:
                    raise ValueError('视频解码异常，请使用完整、未损坏的视频。')
                time.sleep(.05)
            if output is not None and output.exists() and output.stat().st_size > MAX_OUTPUT:
                raise ValueError('转换后的视频超过 512 MB，请剪短或缩小视频。')
            errors.seek(0)
            log = errors.read(1024 * 1024).decode('utf-8', errors='replace')
            if process.returncode or _CORRUPTION.search(log):
                if 'Unknown encoder' in log or 'Encoder not found' in log:
                    raise ValueError('视频转换组件不支持 H.264 或 AAC，请重新安装完整客户端。')
                raise ValueError('无法解码这个视频，请使用包含视频画面的完整、未损坏文件。')
            progress.seek(0)
            return log, progress.read(1024 * 1024).decode('utf-8', errors='replace')
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def _metadata(log, progress):
    # Only inspect input stream descriptions; the null decoder's output is rawvideo.
    description = log.split('Output #', 1)[0]
    container = re.search(r'Input #0, ([^,]+(?:,[^, ]+)*), from ', description)
    video = re.search(r'^\s*Stream #0:\d+[^\n]*Video: ([^,\n]+), ([^\n]+)', description, re.M)
    audio = re.search(r'^\s*Stream #0:\d+[^\n]*Audio: ([^,\n]+), ([^\n]+)', description, re.M)
    duration = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', description)
    frames = re.findall(r'^frame=(\d+)', progress, re.M)
    if not container or not _CONTAINERS.intersection(container.group(1).split(',')) or not video:
        raise ValueError('文件没有可读取的视频画面，请选择视频文件。')
    if '(attached pic)' in video.group(0) or not frames or int(frames[-1]) <= 0:
        raise ValueError('文件没有可读取的视频画面，请选择视频文件。')
    dimensions = re.search(r'(?:^|,\s*)(\d+)x(\d+)(?=[ ,\[])', video.group(2))
    if not dimensions:
        raise ValueError('无法读取视频尺寸，请使用完整的视频文件。')
    seconds = (int(duration.group(1)) * 3600 + int(duration.group(2)) * 60
               + float(duration.group(3))) if duration else None
    sample_rate = re.search(r'(\d+) Hz', audio.group(2)) if audio else None
    return {'container': container.group(1), 'videoCodec': video.group(1).split()[0],
            'audioCodec': audio.group(1).split()[0] if audio else None,
            'audioSampleRate': int(sample_rate.group(1)) if sample_rate else None,
            'audioChannels': 2 if audio and ', stereo,' in audio.group(2) else None,
            'pixelFormat': video.group(2).split(',', 1)[0].split('(', 1)[0].strip(),
            'width': int(dimensions.group(1)), 'height': int(dimensions.group(2)),
            'duration': seconds, 'hasAudio': audio is not None, 'frames': int(frames[-1])}


def _fast_start(path):
    """Check MP4 top-level boxes without loading the video into memory."""
    total, moov, mdat = path.stat().st_size, None, None
    with path.open('rb') as stream:
        offset = 0
        while offset + 8 <= total:
            stream.seek(offset)
            size, kind = struct.unpack('>I4s', stream.read(8))
            header = 8
            if size == 1:
                raw = stream.read(8)
                if len(raw) != 8:
                    return False
                size, header = struct.unpack('>Q', raw)[0], 16
            elif size == 0:
                size = total - offset
            if size < header or offset + size > total:
                return False
            if kind == b'moov':
                moov = offset
            if kind == b'mdat' and mdat is None:
                mdat = offset
            offset += size
        return offset == total and moov is not None and mdat is not None and moov < mdat


def transcode(source_path, destination_path):
    """Decode and atomically write H.264/yuv420p + optional AAC MP4.

    The caller supplies isolated input/output paths. No server/store lock is used;
    callers must also keep their locks released while this synchronous job runs.
    All format/conversion failures are ValueError for the API boundary to display.
    """
    source, destination = Path(source_path), Path(destination_path)
    if source.suffix.lower() not in EXTENSIONS:
        raise ValueError('视频格式不支持，请选择 MP4、WebM、MOV、MKV、AVI 或 MPEG。')
    if destination.suffix.lower() != '.mp4' or source.resolve() == destination.resolve():
        raise ValueError('视频转换输出必须为独立的 MP4 文件。')
    if not source.is_file() or not 0 < source.stat().st_size <= MAX_INPUT:
        raise ValueError('上传视频为空或超过 256 MB。')
    if not _slots.acquire(blocking=False):
        raise ValueError('已有视频正在转换，请稍后重试。')
    try:
        ffmpeg = _ffmpeg()
        deadline = time.monotonic() + MAX_SECONDS
        base = [ffmpeg, '-hide_banner', '-nostdin', '-nostats', '-v', 'info',
                '-progress', 'pipe:1', '-xerror', '-err_detect', 'explode',
                '-protocol_whitelist', 'file,pipe']
        # Decode a frame first to reject audio, attached artwork and renamed images.
        log, progress = _run(base + ['-i', str(source), '-map', '0:v:0', '-an',
                                     '-frames:v', '1', '-f', 'null', '-'], deadline)
        _metadata(log, progress)
        with tempfile.TemporaryDirectory(prefix='studio-video-', dir=destination.parent) as temporary:
            output = Path(temporary) / 'converted.mp4'
            _run(base + ['-i', str(source), '-map', '0:v:0', '-map', '0:a:0?',
                         '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-c:v', 'libx264',
                         '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p',
                         '-c:a', 'aac', '-ac', '2', '-ar', '48000',
                         '-movflags', '+faststart',
                         '-f', 'mp4', str(output)], deadline, output)
            if not output.is_file() or output.stat().st_size == 0:
                raise ValueError('视频转换没有生成有效文件，请重试。')
            # Full decode catches incomplete/corrupt output and measures real frames.
            log, progress = _run(base + ['-i', str(output), '-map', '0:v:0',
                                         '-map', '0:a:0?', '-f', 'null', '-'], deadline, output)
            metadata = _metadata(log, progress)
            if (metadata['videoCodec'] != 'h264' or metadata['pixelFormat'] != 'yuv420p'
                    or metadata['audioCodec'] not in (None, 'aac')
                    or metadata['hasAudio'] and (metadata['audioSampleRate'] != 48000
                                                or metadata['audioChannels'] != 2)
                    or metadata['width'] % 2 or metadata['height'] % 2
                    or metadata['duration'] is None or not math.isfinite(metadata['duration'])
                    or metadata['duration'] <= 0 or not _fast_start(output)):
                raise ValueError('视频转换结果不兼容，请重试或更换视频。')
            metadata.update(container='mp4', fastStart=True, size=output.stat().st_size)
            replace_file(output, destination)
            return metadata
    except OSError as error:
        raise ValueError('视频转换组件无法运行或文件无法写入，请检查安装和磁盘空间。') from error
    finally:
        _slots.release()
