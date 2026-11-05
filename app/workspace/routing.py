from django.urls import path

from workspace.consumers import CollabConsumer, WorkspaceConsumer

websocket_urlpatterns = [
    path("ws/workspace/<int:workspace_id>/", WorkspaceConsumer.as_asgi()),
    path(
        "ws/workspace/<int:workspace_id>/collab/<str:target>/<int:target_id>/",
        CollabConsumer.as_asgi(),
    ),
]
