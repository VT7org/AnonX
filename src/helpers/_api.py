#  Copyright (c) 2025 AshokShau
#  Licensed under the GNU AGPL v3.0: https://www.gnu.org/licenses/agpl-3.0.html
#  Part of the TgMusicBot project. All rights reserved where applicable.

import re
from pathlib import Path
from typing import Optional, Union

from src import config
from src.logger import LOGGER
from ._dataclass import MusicTrack, PlatformTracks, TrackInfo
from ._dl_helper import SpotifyDownload
from ._httpx import HttpxClient


class ApiData(MusicService):
    """Handles music data from various streaming platforms through API integration."""

    # URL patterns for supported music services
    URL_PATTERNS = {
        "apple_music": re.compile(
            r"^(https?://)?(music\.apple\.com/([a-z]{2}/)?(album|playlist|song)/[a-zA-Z0-9\-_]+/[0-9]+)(\?.*)?$",
            re.IGNORECASE,
        ),
        "spotify": re.compile(
            r"^(https?://)?(open\.spotify\.com/(track|playlist|album|artist)/[a-zA-Z0-9]+)(\?.*)?$",
            re.IGNORECASE,
        ),
        "soundcloud": re.compile(
            r"^(https?://)?(soundcloud\.com/[a-zA-Z0-9\-_]+/[a-zA-Z0-9\-_]+)(\?.*)?$",
            re.IGNORECASE,
        ),
    }

    def __init__(self, query: Optional[str] = None) -> None:
        """
        Initialize ApiData with an optional query.

        Args:
            query: URL or search query to process
        """
        self.query = self._sanitize_query(query) if query else None
        self.client = HttpxClient()
        self.api_url = config.API_URL.rstrip("/") if config.API_URL else None
        self.api_key = config.API_KEY

    @staticmethod
    def _sanitize_query(query: str) -> str:
        """Clean and normalize the input query."""
        return query.strip().split("?")[0].split("#")[0]

    def is_valid(self, url: Optional[str]) -> bool:
        """
        Check if the URL is from a supported music service.

        Args:
            url: The URL to validate

        Returns:
            bool: True if URL is valid, False otherwise
        """
        if not url or not self.api_url or not self.api_key:
            return False

        return any(pattern.match(url) for pattern in self.URL_PATTERNS.values())

    async def _make_api_request(
        self, endpoint: str, params: Optional[dict] = None
    ) -> Optional[dict]:
        """
        Make authenticated API requests with proper error handling.

        Args:
            endpoint: API endpoint to call
            params: Optional query parameters

        Returns:
            dict: API response or None if failed
        """
        if not self.api_url or not self.api_key:
            LOGGER.error("API configuration missing")
            return None

        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        return await self.client.make_request(url, params=params)

    async def get_recommendations(self, limit: int = 4) -> Optional[PlatformTracks]:
        """
        Get recommended tracks.

        Args:
            limit: Number of recommendations to fetch

        Returns:
            PlatformTracks: Contains recommended tracks or None if failed
        """
        data = await self._make_api_request("recommend_songs", {"lim": limit})
        return self._parse_tracks_response(data) if data else None

    async def get_info(self) -> Optional[PlatformTracks]:
        """
        Get track information from a URL.

        Returns:
            PlatformTracks: Contains track info or None if failed
        """
        if not self.query or not self.is_valid(self.query):
            return None

        # Use new /search/?q= endpoint instead of /get_url
        new_url = f"https://spotify-dl-ss6q.onrender.com/search/?q={self.query}"
        try:
            data = await self.client.make_request(new_url)
            if data and "results" in data:
                return self._parse_tracks_response(data)
        except Exception as e:
            LOGGER.warning(f"New get_info endpoint failed: {e}")

        # Fallback to old endpoint
        data = await self._make_api_request("get_url", {"url": self.query})
        return self._parse_tracks_response(data) if data else None

    async def search(self) -> Optional[PlatformTracks]:
        """
        Search for tracks across platforms.

        Returns:
            PlatformTracks: Contains search results or None if failed
        """
        if not self.query:
            return None

        # If query is a URL, get info instead of searching
        if self.is_valid(self.query):
            return await self.get_info()

        # Try new Spotify search API first
        try:
            new_search_url = f"https://spotify-dl-ss6q.onrender.com/search"
            params = {"q": self.query}
            response = await self.client.make_request(new_search_url, params=params)
            if response and "results" in response and response["results"]:
                return self._parse_tracks_response(response)
        except Exception as e:
            LOGGER.warning(f"New Spotify search API failed: {e}")

        # Fallback to old API
        data = await self._make_api_request("search_track", {"q": self.query})
        return self._parse_tracks_response(data) if data else None

    async def get_track(self) -> Optional[TrackInfo]:
        """
        Get detailed information about a specific track.

        Returns:
            TrackInfo: Detailed track information or None if failed
        """
        if not self.query:
            return None

        data = await self._make_api_request("get_track", {"id": self.query})
        return TrackInfo(**data) if data else None

    async def download_track(
        self, track: TrackInfo, video: bool = False
    ) -> Optional[Union[str, Path, list[Path]]]:
        """
        Download a track based on its platform.

        Args:
            track: TrackInfo object containing track details
            video: Whether to download video (currently unused for API tracks)

        Returns:
            Path/str/list[Path]: Path to a downloaded file, list of paths for playlists, or None if failed
        """
        if not track:
            return None

        try:
            if track.platform.lower() == "spotify":
                # Determine if it's a track or playlist
                is_playlist = "playlist" in track.url.lower()
                if is_playlist:
                    # Use full URL for playlists
                    spotify_api_url = f"https://spotify-dl-ss6q.onrender.com/download/?url={track.url}"
                else:
                    # Construct track URL from track ID
                    track_id = track.id or track.tc
                    if not track_id:
                        raise Exception("No track ID available")
                    spotify_track_url = f"https://open.spotify.com/track/{track_id}"
                    spotify_api_url = f"https://spotify-dl-ss6q.onrender.com/download/?url={spotify_track_url}"

                result = await self.client.download_file(spotify_api_url)
                if result.success:
                    content_type = result.file_path.suffix.lower()
                    if content_type == ".mp3":
                        return result.file_path
                    elif content_type == ".zip":
                        # Extract MP3s from ZIP
                        extracted_files = await SpotifyDownload(track)._extract_zip(result.file_path)
                        return extracted_files
                    else:
                        raise Exception(f"Invalid content type: {content_type}")
                else:
                    raise Exception(f"API request failed: {result.error}")
            # Original non-Spotify logic
            if not track.cdnurl:
                LOGGER.error("No download URL available for track %s", track.tc)
                return None

            download_path = Path(config.DOWNLOADS_DIR) / f"{track.tc}.mp3"
            result = await self.client.download_file(track.cdnurl, download_path)

            if not result.success:
                LOGGER.error("Download failed for track %s: %s", track.tc, result.error)
                return None

            return result.file_path

        except Exception as e:
            LOGGER.warning(
                "Error downloading track %s with new Spotify API: %s, falling back to original",
                getattr(track, "tc", "unknown"),
                str(e),
                exc_info=True,
            )
            # Fallback to original Spotify logic
            if track.platform.lower() == "spotify":
                return await SpotifyDownload(track).process_original()

            LOGGER.error(
                "Error downloading track %s: %s",
                getattr(track, "tc", "unknown"),
                str(e),
                exc_info=True,
            )
            return None

    @staticmethod
    def _parse_tracks_response(data: dict) -> Optional[PlatformTracks]:
        """
        Parse API response into PlatformTracks object.

        Args:
            data: API response data

        Returns:
            PlatformTracks: Contains parsed tracks or None if invalid
        """
        if not data or not isinstance(data, dict) or "results" not in data:
            return None

        valid_tracks = [
            MusicTrack(**track)
            for track in data["results"]
            if track and isinstance(track, dict)
        ]
        return PlatformTracks(tracks=valid_tracks) if valid_tracks else None
