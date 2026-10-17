# YouTube Downloader

A small command-line utility to download YouTube videos using yt-dlp. The script attempts a direct combined download first, and falls back to downloading separate audio and video streams and merging them with ffmpeg if necessary.

## Requirements
- Python 3.8+
- yt-dlp (see requirements.txt)
- ffmpeg (required for merging streams)
- aria2c (optional, improves download throughput if available)

Install Python deps:

    pip install -r requirements.txt

## Usage

Basic:

    python youtube_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID"

Specify output directory:

    python youtube_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID" -o /path/to/output

If run without a URL, the script will prompt for the video URL and output directory.

## Behavior
- Tries to download a single merged file (best video + best audio).
- If direct download fails, downloads best separate streams and uses ffmpeg to merge.
- Filenames are sanitized for filesystem compatibility.

