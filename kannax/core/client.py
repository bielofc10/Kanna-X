
# pylint: disable=missing-module-docstring
#
# Copyright (C) 2020-2021 by KannaXTeam@Github, < https://github.com/KannaXTeam >.
#
# This file is part of < https://github.com/KannaXTeam/KannaX > project,
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/KannaXTeam/KannaX/blob/master/LICENSE >
#
# All rights reserved.

__all__ = ['KannaX']

import os
import time
import signal
import asyncio
import importlib
from types import ModuleType
from typing import List, Awaitable, Any, Optional, Union

from pyrogram import idle

from kannax import Config, logbot, logging
from kannax.utils import time_formatter
from kannax.utils.exceptions import KannaXBotNotFound
from kannax.plugins import get_all_plugins
from .methods import Methods
from .ext import RawClient, pool
from .database import _close_db

_LOG = logging.getLogger(__name__)
_LOG_STR = "<<<!  #####  %s  #####  !>>>"

_IMPORTED: List[ModuleType] = []
_INIT_TASKS: List[asyncio.Task] = []
_START_TIME = time.time()
_SEND_SIGNAL = False


async def _complete_init_tasks() -> None:
    if not _INIT_TASKS:
        return
    await asyncio.gather(*_INIT_TASKS)
    _INIT_TASKS.clear()


class _AbstractKannaX(Methods, RawClient):
    @property
    def is_bot(self) -> bool:
        """ returns client is bot or not """
        if self._bot is not None:
            return hasattr(self, 'ubot')
        return bool(Config.BOT_TOKEN)

    @property
    def uptime(self) -> str:
        """ returns kannax uptime """
        return time_formatter(time.time() - _START_TIME)

    async def finalize_load(self) -> None:
        """ finalize the plugins load """
        await asyncio.gather(_complete_init_tasks(), self.manager.init())

    async def load_plugin(self, name: str, reload_plugin: bool = False) -> None:
        """ Load plugin to KannaX """
        _LOG.debug(_LOG_STR, f"Importing {name}")
        _IMPORTED.append(
            importlib.import_module(f"kannax.plugins.{name}"))
        if reload_plugin:
            _IMPORTED[-1] = importlib.reload(_IMPORTED[-1])
        plg = _IMPORTED[-1]
        self.manager.update_plugin(plg.__name__, plg.__doc__)
        if hasattr(plg, '_init'):
            # pylint: disable=protected-access
            if asyncio.iscoroutinefunction(plg._init):
                _INIT_TASKS.append(self.loop.create_task(plg._init()))
        _LOG.debug(_LOG_STR, f"Imported {_IMPORTED[-1].__name__} Plugin Successfully")

    async def _load_plugins(self) -> None:
        _IMPORTED.clear()
        _INIT_TASKS.clear()
        logbot.edit_last_msg("Importando todos os plugins", _LOG.info, _LOG_STR)
        for name in get_all_plugins():
            try:
                await self.load_plugin(name)
            except ImportError as i_e:
                _LOG.error(_LOG_STR, f"[{name}] - {i_e}")
        await self.finalize_load()
        _LOG.info(_LOG_STR, f"Imported ({len(_IMPORTED)}) Plugins => "
                  + str([i.__name__ for i in _IMPORTED]))

    async def reload_plugins(self) -> int:
        """ Reload all Plugins """
        self.manager.clear_plugins()
        reloaded: List[str] = []
        _LOG.info(_LOG_STR, "Reloading All Plugins")
        for imported in _IMPORTED:
            try:
                reloaded_ = importlib.reload(imported)
            except ImportError as i_e:
                _LOG.error(_LOG_STR, i_e)
            else:
                reloaded.append(reloaded_.__name__)
        _LOG.info(_LOG_STR, f"Reloaded {len(reloaded)} Plugins => {reloaded}")
        await self.finalize_load()
        return len(reloaded)


class KannaXBot(_AbstractKannaX):
    """ KannaX Bot """
    def __init__(self, **kwargs) -> None:
        _LOG.info(_LOG_STR, "Definindo configurações")
        super().__init__(session_name=":memory:", **kwargs)

    @property
    def ubot(self) -> 'KannaX':
        """ returns userbot """
        return self._bot


class KannaX(_AbstractKannaX):
    """ KannaX, the userbot """

    has_bot = bool(Config.BOT_TOKEN)

    def __init__(self, **kwargs) -> None:
        _LOG.info(_LOG_STR, "Configurando KannaX")
        kwargs = {
            'api_id': Config.API_ID,
            'api_hash': Config.API_HASH,
            'workers': Config.WORKERS
        }
        if Config.BOT_TOKEN:
            kwargs['bot_token'] = Config.BOT_TOKEN
        if Config.HU_STRING_SESSION and Config.BOT_TOKEN:
            RawClient.DUAL_MODE = True
            kwargs['bot'] = KannaXBot(bot=self, **kwargs)
        kwargs['session_name'] = Config.HU_STRING_SESSION or ":memory:"
        super().__init__(**kwargs)
        self.executor.shutdown()
        self.executor = pool._get()  # pylint: disable=protected-access

    @property
    def bot(self) -> Union['KannaXBot', 'KannaX']:
        """ returns kannaxbot """
        if self._bot is None:
            if Config.BOT_TOKEN:
                return self
            raise KannaXBotNotFound("Need BOT_TOKEN ENV!")
        return self._bot

    async def start(self) -> None:
        """ start client and bot """
        _LOG.info(_LOG_STR, "Iniciando KannaX")
        await super().start()
        if self._bot is not None:
            _LOG.info(_LOG_STR, "Iniciando X-Bot")
            await self._bot.start()
        await self._load_plugins()

    async def stop(self) -> None:  # pylint: disable=arguments-differ
        """ stop client and bot """
        if self._bot is not None:
            _LOG.info(_LOG_STR, "Parando X-Bot")
            await self._bot.stop()
        _LOG.info(_LOG_STR, "Parando KannaX")
        await super().stop()
        _close_db()
        pool._stop()  # pylint: disable=protected-access

    def begin(self, coro: Optional[Awaitable[Any]] = None) -> None:
        """ start kannax """
        lock = asyncio.Lock()
        running_tasks: List[asyncio.Task] = []

        async def _finalize() -> None:
            async with lock:
                for t in running_tasks:
                    t.cancel()
                if self.is_initialized:
                    await self.stop()
                else:
                    _close_db()
                    pool._stop()  # pylint: disable=protected-access
            # pylint: disable=expression-not-assigned
            [t.cancel() for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            await self.loop.shutdown_asyncgens()
            self.loop.stop()
            _LOG.info(_LOG_STR, "Loop Stopped !")

        async def _shutdown(_sig: signal.Signals) -> None:
            global _SEND_SIGNAL  # pylint: disable=global-statement
            _LOG.info(_LOG_STR, f"Received Stop Signal [{_sig.name}], Desligando KannaX ...")
            await _finalize()
            if _sig == _sig.SIGUSR1:
                _SEND_SIGNAL = True

        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT, signal.SIGUSR1):
            self.loop.add_signal_handler(
                sig, lambda _sig=sig: self.loop.create_task(_shutdown(_sig)))
        self.loop.run_until_complete(self.start())
        for task in self._tasks:
            running_tasks.append(self.loop.create_task(task()))
        logbot.edit_last_msg("KannaX foi iniciado com sucesso !")
        logbot.end()
        mode = "[DUAL]" if RawClient.DUAL_MODE else "[BOT]" if Config.BOT_TOKEN else "[USER]"
        try:
            if coro:
                _LOG.info(_LOG_STR, f"Running Coroutine - {mode}")
                self.loop.run_until_complete(coro)
            else:
                _LOG.info(_LOG_STR, f"KannaX - {mode}")
                idle()
            self.loop.run_until_complete(_finalize())
        except (asyncio.exceptions.CancelledError, RuntimeError):
            pass
        finally:
            self.loop.close()
            _LOG.info(_LOG_STR, "Loop Closed !")
            if _SEND_SIGNAL:
                os.kill(os.getpid(), signal.SIGUSR1)