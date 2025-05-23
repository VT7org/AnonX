# Copyright (c) 2025 AshokShau
# Licensed under the GNU AGPL v3.0: https://www.gnu.org/licenses/agpl-3.0.html
# Part of the TgMusicBot project. All rights reserved where applicable.

import asyncio
import os
import random
import re
from pathlib import Path
from typing import Any, Optional, Dict, Union

from py_yt import Playlist, VideosSearch

from src.helpers import MusicTrack, PlatformTracks, TrackInfo
from src.logger import LOGGER
from ._downloader import MusicService
from ._httpx import HttpxClient
from ..config import API_URL, API_KEY, DOWNLOADS_DIR, PROXY


class YouTubeUtils:
    """Utility class for YouTube-related operations."""

    # Compile regex patterns once at class level
    YOUTUBE_VIDEO_PATTERN = re.compile(
        r"^(?:https?://)?(?:www\.)?(?:youtube\.com|music\.youtube\.com|youtu\.be)/"
        r"(?:watch\?v=|embed/|v/|shorts/)?([\w-]{11})(?:\?|&|$)",
        re.IGNORECASE,
    )
    YOUTUBE_PLAYLIST_PATTERN = re.compile(
        r"^(?:https?://)?(?:www\.)?(?:youtube\.com|music\.youtube\.com)/"
        r"(?:playlist|watch)\?.*\blist=([\w-]+)",
        re.IGNORECASE,
    )
    YOUTUBE_SHORTS_PATTERN = re.compile(
        r"^(?:https?://)?(?:www\.)?youtube\.com/shorts/([\w-]+)",
        re.IGNORECASE,
    )

    @staticmethod
    def clean_query(query: str) -> str:
        """Clean the query by removing unnecessary parameters."""
        return query.split("&")[0].split("#")[0].strip()

    @staticmethod
    def is_valid_url(url: Optional[str]) -> bool:
        """
        Check if the URL is a valid YouTube URL.

        Args:
            url: The URL to validate

        Returns:
            bool: True if valid YouTube URL, False otherwise
        """
        if not url:
            return False
        return any(
            pattern.match(url)
            for pattern in (
                YouTubeUtils.YOUTUBE_VIDEO_PATTERN,
                YouTubeUtils.YOUTUBE_PLAYLIST_PATTERN,
                YouTubeUtils.YOUTUBE_SHORTS_PATTERN,
            )
        )

    @staticmethod
    def _extract_video_id(url: str) -> Optional[str]:
        """Extract video ID from various YouTube URL formats."""
        for pattern in (
                YouTubeUtils.YOUTUBE_VIDEO_PATTERN,
                YouTubeUtils.YOUTUBE_SHORTS_PATTERN,
        ):
            if match := pattern.match(url):
                return match.group(1)
        return None

    @staticmethod
    async def normalize_youtube_url(url: str) -> Optional[str]:
        """Normalize different YouTube URL formats to standard watch URL."""
        if not url:
            return None

        # Handle youtu.be short links
        if "youtu.be/" in url:
            video_id = url.split("youtu.be/")[1].partition("?")[0].partition("#")[0]
            return f"https://www.youtube.com/watch?v={video_id}"

        # Handle YouTube shorts
        if "youtube.com/shorts/" in url:
            video_id = url.split("youtube.com/shorts/")[1].split("?")[0]
            return f"https://www.youtube.com/watch?v={video_id}"

        return url

    @staticmethod
    def create_platform_tracks(data: Dict[str, Any]) -> PlatformTracks:
        """Create PlatformTracks object from data."""
        if not data or not data.get("results"):
            return PlatformTracks(tracks=[])

        valid_tracks = [
            MusicTrack(**track)
            for track in data["results"]
            if track and track.get("id")
        ]
        return PlatformTracks(tracks=valid_tracks)

    @staticmethod
    def format_track(track_data: Dict[str, Any]) -> Dict[str, Any]:
        """Format track data into a consistent structure."""
        duration = track_data.get("duration", "0:00")
        if isinstance(duration, dict):
            duration = duration.get("secondsText", "0:00")

        # Get the highest quality thumbnail
        cover_url = ""
        if thumbnails := track_data.get("thumbnails"):
            for thumb in reversed(thumbnails):
                if url := thumb.get("url"):
                    cover_url = url
                    break

        return {
            "id": track_data.get("id", ""),
            "name": track_data.get("title", "Unknown Title"),
            "duration": YouTubeUtils.duration_to_seconds(duration),
            "artist": track_data.get("channel", {}).get("name", "Unknown Artist"),
            "cover": cover_url,
            "year": 0,
            "url": f"https://www.youtube.com/watch?v={track_data.get('id', '')}",
            "platform": "youtube",
        }

    @staticmethod
    async def create_track_info(track_data: Dict[str, Any]) -> TrackInfo:
        """Create TrackInfo from formatted track data."""
        return TrackInfo(
            cdnurl="None",
            key="None",
            name=track_data.get("name", "Unknown Title"),
            artist=track_data.get("artist", "Unknown Artist"),
            tc=track_data.get("id", ""),
            album="YouTube",
            cover=track_data.get("cover", ""),
            lyrics="None",
            duration=track_data.get("duration", 0),
            platform="youtube",
            url=f"https://youtube.com/watch?v={track_data.get('id', '')}",
            year=track_data.get("year", 0),
        )

    @staticmethod
    def duration_to_seconds(duration: str) -> int:
        """
        Convert duration string (HH:MM:SS or MM:SS) to seconds.

        Args:
            duration: Time string to convert

        Returns:
            int: Duration in seconds
        """
        if not duration:
            return 0

        try:
            parts = list(map(int, duration.split(":")))
            if len(parts) == 3:  # HH:MM:SS
                return parts[0] * 3600 + parts[1] * 60 + parts[2]
            return parts[0] * 60 + parts[1] if len(parts) == 2 else parts[0]
        except (ValueError, AttributeError):
            return 0

    @staticmethod
    async def get_cookie_file() -> Optional[str]:
        """Get a random cookie file from the 'cookies' directory."""
        cookie_dir = "cookies"
        try:
            if not os.path.exists(cookie_dir):
                LOGGER.warning("Cookie directory '%s' does not exist.", cookie_dir)
                return None

            files = await asyncio.to_thread(os.listdir, cookie_dir)
            cookies_files = [f for f in files if f.endswith(".txt")]

            if not cookies_files:
                LOGGER.warning("No cookie files found in '%s'.", cookie_dir)
                return None

            random_file = random.choice(cookies_files)
            return os.path.join(cookie_dir, random_file)
        except Exception as e:
            LOGGER.warning("Error accessing cookie directory: %s", e)
            return None
    @staticmethod
    async def fetch_oembed_data(url: str) -> Optional[dict[str, Any]]:
        client = HttpxClient()
        oembed_url = f"https://www.youtube.com/oembed?url={url}&format=json"
        data = await client.make_request(oembed_url, max_retries=1)
        if data:
            video_id = url.split("v=")[1]
            return {
                "results": [
                    {
                        "id": video_id,
                        "name": data.get("title"),
                        "duration": 0,
                        "artist": data.get("author_name", ""),
                        "cover": data.get("thumbnail_url", ""),
                        "year": 0,
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "platform": "youtube",
                    }
                ]
            }
        return None

    @staticmethod
    async def download_with_api(video_id: str) -> Optional[Path]:
        """
        Download audio using the API.
        """
        dl = await HttpxClient().download_file(f"{API_URL}/yt?id={video_id}")
        return dl.file_path if dl.success else None

    @staticmethod
    async def download_with_yt_dlp(video_id: str, video: bool) -> Optional[str]:
        """Download using yt-dlp with appropriate parameters."""
        output_template = f"{DOWNLOADS_DIR}/%(id)s.%(ext)s"
        cmd = [
            "yt-dlp",
            "--no-warnings",
            "--quiet",
            "--geo-bypass",
            "--retries", "2",
            "--continue",
            "--no-part",
            "-o", output_template,
        ]

        if video:
            cmd.extend([
                "-f", "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio[ext=m4a])",
                "--merge-output-format", "mp4",
            ])
        else:
            cmd.extend(["-f", "bestaudio[ext=m4a]/bestaudio/best"])

        if PROXY:
            cmd.extend(["--proxy", PROXY])
        elif cookie_file := await YouTubeUtils.get_cookie_file():
            cmd.extend(["--cookies", cookie_file])

        video_url = f"https://www.youtube.com/watch?v={video_id}"
        cmd.extend([video_url, "--print", "after_move:filepath"])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                error_msg = stderr.decode().strip()
                LOGGER.error("Failed to download: %s", error_msg)
                return None

            if downloaded_path := stdout.decode().strip():
                LOGGER.info("Downloaded: %s", downloaded_path)
                return downloaded_path
            return None

        except Exception as e:
            LOGGER.error("Unexpected error while downloading: %r", e)
            return None


class YouTubeData(MusicService):
    """A class to handle YouTube music data fetching and processing."""

    def __init__(self, query: Optional[str] = None) -> None:
        """
        Initialize YouTubeData with an optional query.

        Args:
            query: The search query or YouTube URL to process
        """
        self.client = HttpxClient()
        self.query = YouTubeUtils.clean_query(query) if query else None

    def is_valid(self, url: Optional[str]) -> bool:
        """Check if URL is valid using YouTubeUtils."""
        return YouTubeUtils.is_valid_url(url)

    async def get_info(self) -> Optional[PlatformTracks]:
        """Get track information from YouTube URL."""
        if not self.query or not self.is_valid(self.query):
            return None

        try:
            data = await self._fetch_data(self.query)
            return YouTubeUtils.create_platform_tracks(data) if data else None
        except Exception as e:
            LOGGER.error(f"Error getting info for {self.query}: {e!r}")
            return None

    async def search(self) -> Optional[PlatformTracks]:
        """Search for tracks on YouTube."""
        if not self.query:
            return None

        if self.is_valid(self.query):
            return await self.get_info()

        try:
            search = VideosSearch(self.query, limit=5)
            results = await search.next()
            if not results or not results.get("result"):
                return None

            tracks = [YouTubeUtils.format_track(video) for video in results["result"]]
            return PlatformTracks(tracks=[MusicTrack(**track) for track in tracks])
        except Exception as e:
            LOGGER.error(f"Error searching for '{self.query}': {e!r}")
            return None

    async def get_track(self) -> Optional[TrackInfo]:
        """Get detailed track information."""
        if not self.query:
            return None

        try:
            url = (self.query if self.query.startswith(("http://", "https://")) else f"https://youtube.com/watch?v={self.query}")
            data = await self._fetch_data(url)
            if not data or not data.get("results"):
                return None

            return await YouTubeUtils.create_track_info(data["results"][0])
        except Exception as e:
            LOGGER.error(f"Error fetching track {self.query}: {e!r}")
            return None

    async def download_track(self, track: TrackInfo, video: bool = False) -> Union[Path, str, None]:
        """
        Download a YouTube track.

        Args:
            track: TrackInfo object containing track details
            video: Whether to download video (True) or audio only (False)

        Returns:
            str: Path to downloaded file or None if failed
        """
        if not track:
            return None

        try:
            if not video and API_URL and API_KEY:
                if file_path := await YouTubeUtils.download_with_api(track.tc):
                    return file_path

            return await YouTubeUtils.download_with_yt_dlp(track.tc, video)
        except Exception as e:
            LOGGER.error(f"Error downloading track {track.name}: {e!r}")
            return None

    async def get_recommendations(self) -> Optional[PlatformTracks]:
        """Get recommended tracks (not implemented)."""
        return None

    async def _fetch_data(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Fetch data based on URL type (video or playlist).

        Args:
            url: YouTube URL to fetch data from

        Returns:
            dict: Contains track data or None if failed
        """
        try:
            if YouTubeUtils.YOUTUBE_PLAYLIST_PATTERN.match(url):
                LOGGER.debug(f"Fetching playlist data: {url}")
                return await self._get_playlist_data(url)

            LOGGER.debug(f"Fetching video data: {url}")
            return await self._get_video_data(url)
        except Exception as e:
            LOGGER.error(f"Error fetching data from {url}: {e!r}")
            return None

    @staticmethod
    async def _get_video_data(url: str) -> Optional[Dict[str, Any]]:
        """Get YouTube video data from the URL."""
        normalized_url = await YouTubeUtils.normalize_youtube_url(url)
        if not normalized_url:
            return None

        if data := await YouTubeUtils.fetch_oembed_data(normalized_url):
            return data

        try:
            search = VideosSearch(normalized_url, limit=1)
            results = await search.next()
            if not results or not results.get("result"):
                return None

            return {"results": [YouTubeUtils.format_track(results["result"][0])]}
        except Exception as e:
            LOGGER.error(f"Error searching video: {e!r}")
            return None


    @staticmethod
    async def _get_playlist_data(url: str) -> Optional[Dict[str, Any]]:
        """Get YouTube playlist data."""
        try:
            playlist = await Playlist.getVideos(url)
            if not playlist or not playlist.get("videos"):
                return None

            return {
                "results": [
                    YouTubeUtils.format_track(track)
                    for track in playlist["videos"]
                    if track.get("id")  # Only include valid tracks
                ]
            }
        except Exception as e:
            LOGGER.error(f"Error getting playlist: {e!r}")
            return None
