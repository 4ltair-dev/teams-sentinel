"""Local HTTP Web Bridge between Teams Browser Userscript and Telegram Bot.

Runs on 127.0.0.1:8765 to receive chat events (like Auto-Plus triggers)
and queue outgoing messages from Telegram to Teams chat.
"""

import asyncio
import json
import logging
import time
from typing import Callable, Dict, List, Optional
from aiohttp import web

from config import config

logger = logging.getLogger("TeamsSentinel.WebBridge")

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


class WebBridge:
    def __init__(self, on_chat_event: Optional[Callable[[str, Dict], None]] = None):
        self.on_chat_event = on_chat_event
        self.outgoing_queue: List[str] = []
        self.last_heartbeat: float = 0.0
        self.browser_chat_title: Optional[str] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._lock = asyncio.Lock()

    def is_browser_connected(self) -> bool:
        """Browser is considered connected if a heartbeat was received within last 10 seconds."""
        return (time.time() - self.last_heartbeat) < 10.0

    async def queue_message(self, text: str):
        """Queues a message to be sent to Teams chat by the browser userscript."""
        async with self._lock:
            self.outgoing_queue.append(text)
            logger.info(f"Queued message for Teams chat: '{text}' (queue length: {len(self.outgoing_queue)})")

    async def handle_options(self, request: web.Request) -> web.Response:
        return web.Response(headers=CORS_HEADERS)

    async def handle_status(self, request: web.Request) -> web.Response:
        connected = self.is_browser_connected()
        data = {
            "status": "ok",
            "browser_connected": connected,
            "browser_chat_title": self.browser_chat_title,
            "auto_plus_enabled": config.auto_plus_enabled,
            "auto_plus_threshold": config.auto_plus_threshold,
            "auto_plus_window_seconds": config.auto_plus_window_seconds,
            "auto_greeting_enabled": config.auto_greeting_enabled,
            "auto_greeting_threshold": config.auto_greeting_threshold,
            "pending_outgoing": len(self.outgoing_queue),
        }
        return web.json_response(data, headers=CORS_HEADERS)

    async def handle_heartbeat(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
            self.browser_chat_title = body.get("chat_title")
        except Exception:
            pass
        self.last_heartbeat = time.time()
        return web.json_response({"status": "ok"}, headers=CORS_HEADERS)

    async def handle_outgoing(self, request: web.Request) -> web.Response:
        """Returns and flushes all queued outgoing messages."""
        self.last_heartbeat = time.time()
        async with self._lock:
            messages = list(self.outgoing_queue)
            self.outgoing_queue.clear()
        return web.json_response({"messages": messages}, headers=CORS_HEADERS)

    async def handle_chat_event(self, request: web.Request) -> web.Response:
        """Handles events from Teams userscript, e.g. auto_plus triggered."""
        self.last_heartbeat = time.time()
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        event_type = payload.get("type", "unknown")
        logger.warning(f"Received Teams chat event '{event_type}': {payload}")

        if self.on_chat_event:
            try:
                res = self.on_chat_event(event_type, payload)
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception as e:
                logger.error(f"Error executing on_chat_event callback: {e}")

        return web.json_response({"status": "received"}, headers=CORS_HEADERS)

    async def start(self):
        """Starts the local web bridge HTTP server."""
        app = web.Application()
        app.router.add_options("/{tail:.*}", self.handle_options)
        app.router.add_get("/api/status", self.handle_status)
        app.router.add_get("/api/outgoing", self.handle_outgoing)
        app.router.add_post("/api/heartbeat", self.handle_heartbeat)
        app.router.add_post("/api/chat_event", self.handle_chat_event)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", config.bridge_port)
        await self._site.start()
        logger.info(f"WebBridge server listening on http://127.0.0.1:{config.bridge_port}")

    async def stop(self):
        """Stops the local web bridge HTTP server."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            logger.info("WebBridge server stopped.")


# Default instance
web_bridge = WebBridge()
