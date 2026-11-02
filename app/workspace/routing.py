from django.urls import path

from workspace.consumers import WorkspaceConsumer

websocket_urlpatterns = [
    path("ws/workspace/<int:workspace_id>/", WorkspaceConsumer.as_asgi()),
]
