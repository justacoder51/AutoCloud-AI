"""Loopback-only developer proxy for viewing an IAM-private Cloud Run dashboard.

Uses existing ADC in memory; never saves or exposes the developer's ID token.
"""

import argparse
import asyncio
import logging
from threading import Lock
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response


def create_proxy(target: str, token_provider=None):
    parsed = urlsplit(target)
    if (parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".run.app")
            or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")):
        raise ValueError("An HTTPS Cloud Run origin is required")
    target = target.rstrip("/")
    @asynccontextmanager
    async def lifespan(application):
        async with httpx.AsyncClient(timeout=60, trust_env=True, follow_redirects=False) as client:
            application.state.upstream = client
            yield

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    credentials = None
    lock = Lock()

    def token():
        nonlocal credentials
        if token_provider:
            return token_provider()
        import google.auth
        from google.auth.transport.requests import Request as AuthRequest

        with lock:
            if credentials is None:
                credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            if not credentials.valid or not getattr(credentials, "id_token", None):
                credentials.refresh(AuthRequest())
            value = getattr(credentials, "id_token", None)
            if not value:
                raise ValueError("Developer ADC did not provide an ID token; use gcloud run services proxy")
            return value

    def allowed(connection):
        if not connection.client or connection.client.host not in {"127.0.0.1", "::1", "testclient"}:
            return False
        if connection.headers.get("sec-fetch-site") == "cross-site":
            return False
        origin = connection.headers.get("origin")
        return not origin or origin == "http://" + connection.headers.get("host", "")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"])
    async def forward(request: Request, path: str):
        if not allowed(request):
            return Response("Local access only", status_code=403)
        try:
            identity = await asyncio.to_thread(token)
            headers = {"Authorization": "Bearer " + identity}
            for key in ("cookie", "accept", "content-type", "x-xsrftoken"):
                if key in request.headers:
                    headers[key] = request.headers[key]
            result = await request.app.state.upstream.request(
                request.method, target + "/" + path, params=request.query_params, headers=headers)
            response = Response(result.content, status_code=result.status_code)
            response.raw_headers = [(k, v) for k, v in result.headers.raw if k.lower() not in {
                b"content-length", b"content-encoding", b"transfer-encoding", b"connection",
                b"authorization", b"www-authenticate",
            }]
            return response
        except Exception as error:
            logging.getLogger(__name__).warning("Private HTTP proxy failed: %s", type(error).__name__)
            return Response("Private dashboard connection unavailable", status_code=502)

    @app.websocket("/{path:path}")
    async def websocket_forward(websocket: WebSocket, path: str):
        if not allowed(websocket):
            await websocket.close(code=1008)
            return
        try:
            from websockets.asyncio.client import connect

            identity = await asyncio.to_thread(token)
            headers = {"Authorization": "Bearer " + identity}
            if websocket.headers.get("cookie"):
                headers["Cookie"] = websocket.headers["cookie"]
            protocols = [p.strip() for p in websocket.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
            suffix = "?" + websocket.url.query if websocket.url.query else ""
            async with connect(target.replace("https://", "wss://", 1) + "/" + path + suffix,
                               additional_headers=headers, subprotocols=protocols,
                               origin=target, max_size=32 * 1024 * 1024, proxy=True) as upstream:
                await websocket.accept(subprotocol=upstream.subprotocol)

                async def send_upstream():
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            break
                        await upstream.send(message.get("bytes") if message.get("bytes") is not None else message["text"])

                async def send_browser():
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)

                tasks = [asyncio.create_task(send_upstream()), asyncio.create_task(send_browser())]
                _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as error:
            logging.getLogger(__name__).warning("Private WebSocket proxy failed: %s", type(error).__name__)
            try:
                await websocket.close(code=1011)
            except Exception:
                pass

    return app


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--port", type=int, default=8503)
    args = parser.parse_args()
    uvicorn.run(create_proxy(args.url), host="127.0.0.1", port=args.port, access_log=False)
