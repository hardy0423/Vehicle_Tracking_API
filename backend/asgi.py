import os
import threading
import logging
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator
from dotenv import load_dotenv
load_dotenv()

os.environ.setdefault('DJANGO_SETTINGS_MODULE', os.getenv('SETTINGS_PROJECT'))

# Setup logger
logger = logging.getLogger(__name__)


django_asgi_app = get_asgi_application()


from .routing import websocket_urlpatterns
from server.tcp_communication_server import TCPServerConsumer

tcp_server_consumer = TCPServerConsumer()

def start_tcp_server():
    """Start the TCP server in a background thread."""
    try:
        logger.info("Starting TCP server...")
        tcp_server_consumer.start_server()
    except Exception as e:
        logger.error(f"Failed to start TCP server: {e}", exc_info=True)

async def startup_event():
    """Start the TCP server when ASGI starts."""
    threading.Thread(target=start_tcp_server, daemon=True).start()
    logger.info("TCP server started in background.")

async def shutdown_event():
    """Gracefully stop TCP server on ASGI shutdown."""
    logger.info("Shutting down TCP server...")
    tcp_server_consumer.stop_server()

async def lifespan(scope, receive, send):
    """ASGI lifespan protocol handler."""
    if scope["type"] == "lifespan":
        message = await receive()
        if message["type"] == "lifespan.startup":
            await startup_event()
            await send({"type": "lifespan.startup.complete"})

        message = await receive()
        if message["type"] == "lifespan.shutdown":
            await shutdown_event()
            await send({"type": "lifespan.shutdown.complete"})

# Core ASGI application
_asgi_core = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
    "lifespan": lifespan,
})

application = _asgi_core
