import argparse
import logging
import os
import ssl
from aiohttp import web
import WebRTCManager

ROOT = os.path.dirname(__file__)


async def index(request):
    content = open(os.path.join(ROOT, "public/index.html"), "r").read()
    return web.Response(content_type="text/html", text=content)


async def javascript(request):
    content = open(os.path.join(ROOT, "public/client.js"), "r").read()
    return web.Response(content_type="application/javascript", text=content)


async def offer(request):
    webrtc_offer = await WebRTCManager.offer(request)

    return web.Response(
        content_type="application/json",
        text=webrtc_offer
    )


async def on_shutdown(app):
    await WebRTCManager.on_shutdown()


def start_app(args):
    if args.verbose:
        WebRTCManager.init(logging.DEBUG)
    else:
        WebRTCManager.init(logging.INFO)

    if args.cert_file:
        ssl_context = ssl.SSLContext()
        ssl_context.load_cert_chain(args.cert_file, args.key_file)
    else:
        ssl_context = None

    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", index)
    app.router.add_get("/client.js", javascript)
    app.router.add_post("/offer", offer)
    web.run_app(
        app, access_log=None, host=args.host, port=args.port, ssl_context=ssl_context
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="WebRTC audio / video / data-channels demo"
    )
    parser.add_argument("--cert-file", help="SSL certificate file (for HTTPS)")
    parser.add_argument("--key-file", help="SSL key file (for HTTPS)")
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host for HTTP server (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="Port for HTTP server (default: 8080)"
    )
    parser.add_argument("--record-to", help="Write received media to a file."),
    parser.add_argument("--verbose", "-v", action="count")
    args = parser.parse_args()

    start_app(args)
