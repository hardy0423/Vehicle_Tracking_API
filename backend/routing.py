from django.urls import re_path
from trackings.notifications.consumers import NotificationConsumer
from devices.consumers import DeviceStatusConsumer

websocket_urlpatterns = [
    re_path(r'ws/notifications/$', NotificationConsumer.as_asgi()),
    re_path(r'ws/device-status/$', DeviceStatusConsumer.as_asgi()),
]