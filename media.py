"""Browser playback support. Original media is never modified by preparation."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from threading import Lock

from PIL import Image, ImageOps

PHOTO_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.avif'}
RAW_EXTS = {'.cr2', '.cr3', '.crw', '.nef', '.nrw', '.arw', '.sr2', '.srf',
            '.orf', '.rw2', '.raf', '.pef', '.dng', '.raw', '.rwl', '.3fr', '.iiq'}
EXTRA_PHOTO_EXTS = {'.tif', '.tiff', '.heic', '.heif', '.hif', '.mpo'}
VIDEO_EXTS = {'.mp4', '.mov', '.webm', '.m4v', '.avi', '.mpg', '.mpeg', '.mpe',
              '.mts', '.m2ts', '.m2t', '.mod', '.tod', '.vob', '.dv', '.3gp',
              '.3g2', '.wmv', '.asf', '.mkv', '.ts', '.mxf', '.flv'}
EXTS = PHOTO_EXTS | EXTRA_PHOTO_EXTS | RAW_EXTS | VIDEO_EXTS
log = logging.getLogger(__name__)
# Preparation is deliberately serial to avoid competing CPU-heavy encodes.
prepare_lock = Lock()


class MediaError(Exception):
    pass


def display_name(path: Path) -> str:
    return path.stem


def ffmpeg():
    name = 'ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg'
    bundled = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'ffmpeg' / name
    if bundled.is_file():
        # Some ZIP extractors discard Unix execute bits, including Python's zipfile.
        if os.name != 'nt' and not os.access(bundled, os.X_OK):
            bundled.chmod(bundled.stat().st_mode | 0o100)
        return str(bundled)
    local = Path(sys.executable).with_name(name)
    executable = str(local) if local.is_file() else shutil.which('ffmpeg')
    if executable:
        return executable
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as error:
        raise MediaError('Video decoder is unavailable') from error


def fingerprint(source: Path):
    stat = source.stat()
    return (str(source.resolve()), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def subprocess_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}


@lru_cache(maxsize=2048)
def probe_video(signature):
    result = subprocess.run([ffmpeg(), '-nostdin', '-hide_banner', '-i', signature[0]],
                            capture_output=True, text=True, errors='replace', timeout=45, **subprocess_options())
    lines = result.stderr.splitlines()
    video_line = next((line for line in lines if 'Video:' in line and 'attached pic' not in line), '')
    audio_line = next((line for line in lines if 'Audio:' in line), '')
    video = re.search(r'Video:\s*(\w+)', video_line)
    audio = re.search(r'Audio:\s*(\w+)', audio_line)
    if not video:
        raise MediaError('No readable video stream')
    codec = video.group(1)
    # High-bit-depth H.264 and MPEG-4 Part 2 require a playback encode.
    copy_video = codec in {'h264', 'av1', 'vp9'} and bool(re.search(r'\byuvj?420p\b', video_line))
    return codec, audio.group(1) if audio else None, copy_video


def direct_video(source: Path, signature):
    codec, audio, copy_video = probe_video(signature)
    if source.suffix.lower() == '.webm':
        return codec in {'vp8', 'vp9', 'av1'} and audio in {None, 'opus', 'vorbis'}
    return (source.suffix.lower() in {'.mp4', '.mov', '.m4v'} and copy_video
            and codec in {'h264', 'av1', 'vp9'} and audio in {None, 'aac', 'mp3'})


def convert_photo(source: Path, target: Path):
    if source.suffix.lower() in RAW_EXTS:
        import rawpy
        with rawpy.imread(str(source)) as raw:
            image = Image.fromarray(raw.postprocess(use_camera_wb=True, output_bps=8))
    else:
        if source.suffix.lower() in {'.heic', '.heif', '.hif'}:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original).convert('RGB')
    try:
        image.save(target, 'JPEG', quality=95)
    finally:
        image.close()


def convert_video(source: Path, target: Path, signature, force):
    _, audio, copy_video = probe_video(signature)
    command = [ffmpeg(), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source),
               '-map', '0:V:0', '-map', '0:a:0?', '-sn', '-dn']
    if copy_video and not force:
        command += ['-c:v', 'copy']
    else:
        command += ['-vf', 'bwdif=mode=send_frame:deint=interlaced,scale=trunc(iw/2)*2:trunc(ih/2)*2',
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p']
    command += ['-c:a', 'copy' if audio == 'aac' and not force else 'aac', '-b:a', '192k',
                '-movflags', '+faststart', str(target)]
    result = subprocess.run(command, capture_output=True, text=True, errors='replace', timeout=14400, **subprocess_options())
    if result.returncode:
        log.warning('Playback preparation failed for %s: %s', source, result.stderr[-2000:])
        raise MediaError('Video could not be prepared for playback')


def cache_key(signature, force):
    # Renaming/moving within the library keeps the same media and cached playback.
    identity = signature[1:5]  # device, inode, size, modification time
    return hashlib.sha256(repr(('v2', identity, force)).encode()).hexdigest()


def cached_copies(path: Path, library: Path):
    cache = library / '.elemframe-cache'
    if cache.is_symlink():
        return []
    result = []
    sources = [path] if path.is_file() else path.rglob('*')
    for source in sources:
        if source.is_symlink() or not source.is_file() or source.suffix.lower() not in EXTS:
            continue
        signature = fingerprint(source)
        extension = '.mp4' if source.suffix.lower() in VIDEO_EXTS else '.jpg'
        result.extend(cache / (cache_key(signature, force) + extension) for force in (False, True))
    return result


def playback_path(source: Path, library: Path, force=False) -> Path:
    """Serve supported originals directly; create a hidden compatible copy as needed."""
    extension = source.suffix.lower()
    try:
        signature = fingerprint(source)
        cache = library / '.elemframe-cache'
        if cache.is_symlink():
            raise MediaError('Playback storage is unavailable')
        fallback_key = cache_key(signature, True)
        fallback_path = cache / (fallback_key + ('.mp4' if extension in VIDEO_EXTS else '.jpg'))
        if fallback_path.is_file():
            return fallback_path
        if extension in PHOTO_EXTS and not force:
            return source
        if extension in VIDEO_EXTS and not force and direct_video(source, signature):
            return source
        with prepare_lock:
            cache = library / '.elemframe-cache'
            cache.mkdir(exist_ok=True)
            key = cache_key(signature, force)
            destination = cache / (key + ('.mp4' if extension in VIDEO_EXTS else '.jpg'))
            if destination.is_file():
                return destination
            with tempfile.NamedTemporaryFile(dir=cache, prefix='.preparing-', suffix=destination.suffix, delete=False) as output:
                temporary = Path(output.name)
            try:
                if extension in VIDEO_EXTS:
                    convert_video(source, temporary, signature, force)
                else:
                    convert_photo(source, temporary)
                if fingerprint(source) != signature:
                    raise MediaError('Media changed while preparing playback')
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
            return destination
    except MediaError:
        raise
    except Exception as error:
        log.warning('Cannot prepare %s: %s', source, error)
        raise MediaError('Media could not be displayed') from error


def prepare_import(path: Path, library: Path):
    """Prepare imports recursively without revealing generated files in the manager."""
    issues = []
    paths = [path] if path.is_file() else path.rglob('*')
    for source in paths:
        if (not source.is_file() or source.is_symlink() or source.suffix.lower() not in EXTS
                or any(part.startswith('.') for part in source.relative_to(library).parts)):
            continue
        try:
            playback_path(source, library)
        except MediaError:
            issues.append(display_name(source))
    return issues
