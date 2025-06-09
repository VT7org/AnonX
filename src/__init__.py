#  Copyright (c) 2025 AshokShau
#  Licensed under the GNU AGPL v3.0: https://www.gnu.org/licenses/agpl-3.0.html
#  Part of the TgMusicBot project. All rights reserved where applicable.

import asyncio
import os
import shutil
from datetime import datetime

from pytdbot import Client, types

from src import config
from src.helpers import call, db, start_clients
from src.modules.jobs import InactiveCallManager

__version__ = "1.2.0.dev0"
StartTime = datetime.now()


class Telegram(Client):
    def __init__(self) -> None:
        self._check_config()
        super().__init__(
            token=config.TOKEN,
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            default_parse_mode="html",
            td_verbosity=2,
            td_log=types.LogStreamEmpty(),
            plugins=types.plugins.Plugins(folder="src/modules"),
            files_directory="",
            database_encryption_key="",
            options={"ignore_background_updates": config.IGNORE_BACKGROUND_UPDATES},
        )
        self.call_manager = InactiveCallManager(self)
        self.db = db

    async def start(self) -> None:
        await self.db.ping()
        await start_clients()
        await call.add_bot(self)
        await call.register_decorators()
        # Set up pytgcalls handlers for participant updates
        pytgcalls_client = await call.get_client(0)  # Assuming 0 is a valid chat_id or default
        if not isinstance(pytgcalls_client, types.Error):
            self.call_manager.setup_pytgcalls_handlers(pytgcalls_client)
            self.logger.debug("Pytgcalls handlers set up successfully")
        else:
            self.logger.warning("Failed to get pytgcalls client: %s", pytgcalls_client.message)
        await self.call_manager.start_scheduler()
        await super().start()
        self.logger.info(f"Bot started in {datetime.now() - StartTime} seconds.")
        self.logger.info(f"Version: {__version__}")

    async def stop(self) -> None:
        shutdown_tasks = [
            self.db.close(),
            self.call_manager.stop_scheduler(),
            super().stop(),
        ]
        await asyncio.gather(*shutdown_tasks)

    @staticmethod
    def _check_config() -> None:
        if not config.API_ID or not config.API_HASH or not config.TOKEN:
            raise ValueError("API_ID, API_HASH and TOKEN are required")
        if config.IGNORE_BACKGROUND_UPDATES and os.path.exists("database"):
            shutil.rmtree("database")
        if not isinstance(config.MONGO_URI, str):
            raise TypeError("MONGO_URI must be a string")
        if not config.SESSION_STRINGS:
            raise ValueError("No STRING session provided\n\nAdd STRING session in .env")


client: Telegram = Telegram()
