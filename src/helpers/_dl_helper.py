#  Copyright (c) 2025 AshokShau
#  Licensed under the GNU AGPL v3.0: https://www.gnu.org/licenses/agpl-3.0.html
#  Part of the TgMusicBot project. All rights reserved where applicable.

import asyncio
import os
import subprocess
from typing import Optional, List
from pathlib import Path
import zipfile

import aiofiles
from Crypto.Cipher import AES
from Crypto.Util import Counter

from src import config
from src.helpers._httpx import HttpxClient
from src.logger import LOGGER
from ._dataclass import TrackInfo


async def rebuild_ogg(filename: str) -> None:
    """
    Fixes broken OGG headers.
    """
    if not os.path.exists(filename):
        LOGGER.error("❌ Error: %s not found.", filename)
        return

    try:
        async with aiofiles.open(filename, "r+b") as ogg_file:
            ogg_s = b"OggS"
            zeroes = b"\x00" * 10
            vorbis_start = b"\x01\x1e\x01vorbis"
            channels = b"\x02"
            sample_rate = b"\x44\xac\x00\x00"
            bit_rate = b"\x00\xe2\x04\x00"
            packet_sizes = b"\xb8\x01"

            await ogg_file.seek(0)
            await ogg_file.write(ogg_s)
            await ogg_file.seek(6)
            await ogg_file.write(zeroes)
            await ogg_file.seek(26)
            await ogg_file.write(vorbis_start)
            await ogg_file.seek(39)
            await ogg_file.write(channels)
            await ogg_file.seek(40)
            await ogg_file.write(sample_rate)
            await ogg_file.seek(48)
            await ogg_file.write(bit_rate)
            await ogg_file.seek(56)
            await ogg_file.write(packet_sizes)
            await ogg_file.seek(58)
            await ogg_file.write(ogg_s)
            await ogg_file.seek(62)
            await ogg_file.write(zeroes)
    except Exception as e:
        LOGGER.error("Error rebuilding OGG file %s: %s", filename, e)


class SpotifyDownload:
    def __init__(self, track: TrackInfo):
        self.track = track
        self.client = HttpxClient()
        self.encrypted_file = os.path.join(
            config.DOWNLOADS_DIR, f"{track.tc}.encrypted.ogg"
        )
        self.decrypted_file = os.path.join(
            config.DOWNLOADS_DIR, f"{track.tc}.decrypted.ogg"
        )
        self.output_file = os.path.join(config.DOWNLOADS_DIR, f"{track.tc}.ogg")

    async def decrypt_audio(self) -> None:
        """
        Decrypt the downloaded audio file using a stream-based approach.
        """
        try:
            key = bytes.fromhex(self.track.key)
            iv = bytes.fromhex("72e067fbddcbcf77ebe8bc643f630d93")
            iv_int = int.from_bytes(iv, "big")
            cipher = AES.new(
                key, AES.MODE_CTR, counter=Counter.new(128, initial_value=iv_int)
            )

            chunk_size = 8192  # 8KB chunks
            async with (
                aiofiles.open(self.encrypted_file, "rb") as fin,
                aiofiles.open(self.decrypted_file, "wb") as fout,
            ):
                while chunk := await fin.read(chunk_size):
                    decrypted_chunk = cipher.decrypt(chunk)
                    await fout.write(decrypted_chunk)
        except Exception as e:
            LOGGER.error("Error decrypting audio file: %s", e)
            raise

    async def fix_audio(self) -> None:
        """
        Fix the decrypted audio file using FFmpeg.
        """
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-i",
                self.decrypted_file,
                "-c",
                "copy",
                self.output_file,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode != 0:
                LOGGER.error("FFmpeg error: %s", stderr.decode().strip())
                raise subprocess.CalledProcessError(process.returncode, "ffmpeg")
        except Exception as e:
            LOGGER.error("Error fixing audio file: %s", e)
            raise

    async def _cleanup(self) -> None:
        """
        Cleanup temporary files asynchronously.
        """
        for file in [self.encrypted_file, self.decrypted_file]:
            try:
                if os.path.exists(file):
                    os.remove(file)
            except Exception as e:
                LOGGER.warning("Error removing %s: %s", file, e)

    async def _extract_zip(self, zip_path: Path) -> list[Path]:
        """
        Extract MP3 files from a ZIP archive.

        Args:
            zip_path: Path to the ZIP file

        Returns:
            list[Path]: List of paths to extracted MP3 files
        """
        extracted_files = []
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for file_name in zip_ref.namelist():
                    if file_name.endswith('.mp3'):
                        zip_ref.extract(file_name, path=config.DOWNLOADS_DIR)
                        extracted_files.append(Path(config.DOWNLOADS_DIR) / file_name)
            os.remove(zip_path)  # Clean up ZIP
            LOGGER.info("Extracted %d MP3 files from %s", len(extracted_files), zip_path)
            return extracted_files
        except Exception as e:
            LOGGER.error("Error extracting ZIP %s: %s", zip_path, str(e))
            return []

    async def process_original(self) -> Optional[str]:
        """
        Original Spotify download logic (preserved as fallback).

        Returns:
            Optional[str]: Path to the downloaded file or None if failed
        """
        if os.path.exists(self.output_file):
            LOGGER.info("✅ Found existing file: %s", self.output_file)
            return self.output_file

        _track_id = self.track.tc
        if not self.track.cdnurl or not self.track.key:
            LOGGER.warning("Missing CDN URL or key for track: %s", _track_id)
            return None

        try:
            await self.client.download_file(self.track.cdnurl, self.encrypted_file)
            await self.decrypt_audio()
            await rebuild_ogg(self.decrypted_file)
            await self.fix_audio()
            await self._cleanup()
            LOGGER.info("✅ Successfully processed track: %s", self.output_file)
            return self.output_file
        except Exception as e:
            LOGGER.error("Error processing track %s: %s", _track_id, e)
            await self._cleanup()
            return None
