from __future__ import annotations

import json
import unittest

import httpx

from app.llm import LlmClient


class LlmClientTests(unittest.TestCase):
    def _client_with_transport(self, handler: httpx.MockTransport) -> LlmClient:
        client = LlmClient(
            base_url="http://llm.local/v1",
            model="demo-model",
            fallback_model="",
            api_key="",
            timeout_seconds=10,
            max_tokens=64,
        )
        client._client.close()  # noqa: SLF001 - replace transport for deterministic tests
        client._client = httpx.Client(transport=handler, timeout=10.0)
        return client

    def test_chat_falls_back_to_responses_api_on_404(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/chat/completions":
                return httpx.Response(404, request=request, json={"error": "not found"})
            if request.url.path == "/v1/responses":
                body = json.loads(request.content.decode("utf-8"))
                self.assertEqual(body["input"][0]["role"], "user")
                return httpx.Response(200, request=request, json={"output_text": "pong"})
            self.fail(f"Unexpected URL: {request.url}")

        client = self._client_with_transport(httpx.MockTransport(handler))
        try:
            reply = client.chat([{"role": "user", "content": "ping"}])
        finally:
            client.close()
        self.assertEqual(reply, "pong")
        self.assertEqual(client.api_mode, "responses")

    def test_stream_falls_back_to_responses_api_on_404(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/chat/completions":
                return httpx.Response(404, request=request, json={"error": "not found"})
            if request.url.path == "/v1/responses":
                content = "\n".join(
                    [
                        'data: {"type":"response.output_text.delta","delta":"po"}',
                        'data: {"type":"response.output_text.delta","delta":"ng"}',
                        'data: {"type":"response.completed"}',
                    ]
                )
                headers = {"Content-Type": "text/event-stream"}
                return httpx.Response(200, request=request, headers=headers, content=content)
            self.fail(f"Unexpected URL: {request.url}")

        chunks: list[str] = []
        client = self._client_with_transport(httpx.MockTransport(handler))
        try:
            reply = client.chat_stream([{"role": "user", "content": "ping"}], on_chunk=chunks.append)
        finally:
            client.close()
        self.assertEqual(reply, "pong")
        self.assertEqual("".join(chunks), "pong")
        self.assertEqual(client.api_mode, "responses")

    def test_http_error_contains_request_url(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, request=request, json={"error": "unauthorized"})

        client = self._client_with_transport(httpx.MockTransport(handler))
        try:
            with self.assertRaises(RuntimeError) as ctx:
                client.chat([{"role": "user", "content": "ping"}])
        finally:
            client.close()
        self.assertIn("POST http://llm.local/v1/chat/completions -> HTTP 401", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
