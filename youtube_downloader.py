#!/usr/bin/env python3
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yt_dlp


def build_common_ydl_options() -> dict:
    options = {
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'retries': 10,
        'fragment_retries': 10,
        'file_access_retries': 5,
        'concurrent_fragment_downloads': 8,
        'http_chunk_size': 10 * 1024 * 1024,
    }

    # aria2c can significantly improve throughput for long videos when available.
    if shutil.which('aria2c'):
        options.update({
            'external_downloader': 'aria2c',
            'external_downloader_args': {
                'default': ['-x', '16', '-s', '16', '-k', '1M', '--summary-interval=0'],
            },
        })

    return options


def sanitize_name(value: str) -> str:
    safe = ''.join(ch if ch.isalnum() or ch in {' ', '-', '_', '.'} else '_' for ch in value)
    safe = safe.strip().rstrip('.')
    return safe or 'youtube_video'


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_direct(url: str, output_dir: Path) -> Path:
    output_dir = ensure_directory(output_dir)
    options = {
        **build_common_ydl_options(),
        'outtmpl': str(output_dir / '%(title)s.%(ext)s'),
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'paths': {'home': str(output_dir)},
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)

    title = sanitize_name(info.get('title', 'youtube_video'))
    extensions = ['.mp4', '.mkv', '.webm']
    for ext in extensions:
        candidate = output_dir / f'{title}{ext}'
        if candidate.exists():
            return candidate

    # Fallback for downloads whose filenames are not exactly title.ext
    for path in output_dir.iterdir():
        if path.is_file() and 'youtube' not in path.name.lower():
            if path.suffix.lower() in {'.mp4', '.m4a', '.webm', '.mkv'}:
                return path

    raise FileNotFoundError(f'Could not determine output path for: {url}')


def build_best_formats(info):
    formats = info.get('formats', [])
    if not formats:
        raise ValueError('No downloadable formats were found for this video.')

    video_formats = [
        f for f in formats
        if f.get('vcodec') != 'none' and f.get('acodec') == 'none'
    ]
    audio_formats = [
        f for f in formats
        if f.get('acodec') != 'none' and f.get('vcodec') == 'none'
    ]

    if not video_formats or not audio_formats:
        raise ValueError('This video does not provide separate audio and video streams.')

    video = max(video_formats, key=lambda f: (f.get('height') or 0, f.get('tbr') or 0, f.get('fps') or 0))
    audio = max(audio_formats, key=lambda f: (f.get('tbr') or 0, f.get('abr') or 0))
    return video, audio


def download_separate_streams_and_merge(url: str, output_dir: Path) -> Path:
    output_dir = ensure_directory(output_dir)
    info_options = build_common_ydl_options()
    info = yt_dlp.YoutubeDL(info_options).extract_info(url, download=False)
    title = sanitize_name(info.get('title', 'youtube_video'))
    video, audio = build_best_formats(info)

    with tempfile.TemporaryDirectory(prefix='yt-dlp-') as temp_dir_name:
        temp_dir = Path(temp_dir_name)

        video_download_options = {
            **build_common_ydl_options(),
            'format': video['format_id'],
            'outtmpl': str(temp_dir / 'video.%(ext)s'),
            'paths': {'home': str(temp_dir)},
        }
        audio_download_options = {
            **build_common_ydl_options(),
            'format': audio['format_id'],
            'outtmpl': str(temp_dir / 'audio.%(ext)s'),
            'paths': {'home': str(temp_dir)},
        }

        with yt_dlp.YoutubeDL(video_download_options) as ydl:
            ydl.download([url])

        with yt_dlp.YoutubeDL(audio_download_options) as ydl:
            ydl.download([url])

        video_file = next((p for p in temp_dir.iterdir() if p.name.startswith('video.')), None)
        audio_file = next((p for p in temp_dir.iterdir() if p.name.startswith('audio.')), None)

        if video_file is None or audio_file is None:
            raise FileNotFoundError('Could not locate downloaded video or audio stream.')

        output_path = output_dir / f'{title}.mp4'
        ffmpeg_command = [
            'ffmpeg',
            '-y',
            '-i', str(video_file),
            '-i', str(audio_file),
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-c', 'copy',
            '-movflags', '+faststart',
            '-shortest',
            str(output_path),
        ]
        try:
            subprocess.run(ffmpeg_command, check=True, capture_output=True, text=True)
            return output_path
        except subprocess.CalledProcessError:
            # Some source combinations cannot be stream-copied into MP4.
            transcode_command = [
                'ffmpeg',
                '-y',
                '-i', str(video_file),
                '-i', str(audio_file),
                '-map', '0:v:0',
                '-map', '1:a:0',
                '-c:v', 'libx264',
                '-c:a', 'aac',
                '-movflags', '+faststart',
                '-shortest',
                str(output_path),
            ]
            subprocess.run(transcode_command, check=True, capture_output=True, text=True)
            return output_path


def download_youtube(url: str, output_dir: Path) -> Path:
    output_dir = ensure_directory(output_dir)
    print(f'Downloading: {url}')
    print(f'Output directory: {output_dir}')

    try:
        print('Trying direct single-file download...')
        return download_direct(url, output_dir)
    except Exception as direct_error:
        print(f'Direct download failed: {direct_error}')
        print('Falling back to separate video and audio streams...')

    try:
        return download_separate_streams_and_merge(url, output_dir)
    except Exception as merge_error:
        raise RuntimeError(f'Unable to download video via direct or split-stream fallback: {merge_error}') from merge_error


def prompt_for_value(label: str, default: str | None = None) -> str:
    prompt = label
    if default is not None:
        prompt = f'{label} [{default}]'

    while True:
        value = input(f'{prompt}: ').strip()
        if value:
            return value
        if default is not None:
            return default


def parse_args():
    parser = argparse.ArgumentParser(description='Download a YouTube video into the current folder by default.')
    parser.add_argument('url', nargs='?', help='YouTube video URL to download')
    parser.add_argument(
        '-o',
        '--output-dir',
        type=Path,
        help='Directory to save the downloaded file. Defaults to the current working directory.',
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    url = args.url or prompt_for_value('Enter YouTube video URL')
    output_dir = args.output_dir or Path(prompt_for_value('Enter output folder', str(Path.cwd())))

    if not shutil.which('ffmpeg'):
        print('ffmpeg is required for the split-stream fallback merge step, but it was not found on PATH.', file=sys.stderr)
        return 1

    try:
        result = download_youtube(url, output_dir)
        print(f'File saved to: {result}')
        return 0
    except Exception as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
