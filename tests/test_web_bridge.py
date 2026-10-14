"""Unit tests for Teams Sentinel WebBridge."""

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from config import config
from web_bridge import WebBridge


class TestWebBridge(AioHTTPTestCase):
    async def get_application(self):
        self.bridge = WebBridge()
        self.events_received = []

        def event_cb(event_type, data):
            self.events_received.append((event_type, data))

        self.bridge.on_chat_event = event_cb

        app = web.Application()
        app.router.add_options("/{tail:.*}", self.bridge.handle_options)
        app.router.add_get("/api/status", self.bridge.handle_status)
        app.router.add_get("/api/outgoing", self.bridge.handle_outgoing)
        app.router.add_post("/api/heartbeat", self.bridge.handle_heartbeat)
        app.router.add_post("/api/chat_event", self.bridge.handle_chat_event)
        return app

    @unittest_run_loop
    async def test_status_endpoint(self):
        resp = await self.client.request("GET", "/api/status")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertFalse(data["browser_connected"])
        self.assertEqual(data["auto_plus_threshold"], config.auto_plus_threshold)

    @unittest_run_loop
    async def test_heartbeat_updates_connected_status(self):
        self.assertFalse(self.bridge.is_browser_connected())
        resp = await self.client.request("POST", "/api/heartbeat", json={"chat_title": "Biology Lecture"})
        self.assertEqual(resp.status, 200)
        self.assertTrue(self.bridge.is_browser_connected())
        self.assertEqual(self.bridge.browser_chat_title, "Biology Lecture")

    @unittest_run_loop
    async def test_outgoing_message_queue(self):
        # Queue two messages
        await self.bridge.queue_message("+")
        await self.bridge.queue_message("Я тут, микрофон не работает")

        # Fetch from outgoing endpoint
        resp = await self.client.request("GET", "/api/outgoing")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(len(data["messages"]), 2)
        self.assertEqual(data["messages"][0], "+")
        self.assertEqual(data["messages"][1], "Я тут, микрофон не работает")

        # Second fetch should be empty
        resp2 = await self.client.request("GET", "/api/outgoing")
        data2 = await resp2.json()
        self.assertEqual(len(data2["messages"]), 0)

    @unittest_run_loop
    async def test_chat_event_callback(self):
        payload = {
            "type": "auto_plus",
            "count": 4,
            "authors": ["Иван", "Анна", "Сергей", "Елена"]
        }
        resp = await self.client.request("POST", "/api/chat_event", json=payload)
        self.assertEqual(resp.status, 200)
        self.assertEqual(len(self.events_received), 1)
        event_type, data = self.events_received[0]
        self.assertEqual(event_type, "auto_plus")
        self.assertEqual(data["count"], 4)
        self.assertEqual(len(data["authors"]), 4)


if __name__ == "__main__":
    unittest.main()
