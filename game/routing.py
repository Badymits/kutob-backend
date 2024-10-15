from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("ws/socket-server/<str:username>/<str:code>/", consumers.GameRoomConsumer.as_asgi()),
]