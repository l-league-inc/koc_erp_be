from django.urls import path

from wiki import views

urlpatterns = [
    path("login/", views.login_view, name="wiki-login"),
    path("logout/", views.logout_view, name="wiki-logout"),
    path("p/<str:slug>/", views.page_view, name="wiki-page"),
    path("", views.index_view, name="wiki-index"),
]
