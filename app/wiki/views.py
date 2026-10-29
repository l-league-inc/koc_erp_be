from functools import wraps
from typing import Callable

from django.contrib.auth import authenticate, get_user_model
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from wiki.utils import (
    LOGIN_ERROR_MESSAGE,
    group_pages,
    list_pages,
    load_page,
    search_pages,
)

User = get_user_model()

WIKI_SESSION_KEY = "wiki_user_id"


def _is_wiki_admin(user: User | None) -> bool:
    if user is None:
        return False
    if user.permission_type != User.UserPermissionTypeChoices.ADMIN:
        return False
    if getattr(user, "withdraw_at", None):
        return False
    if user.status == User.UserStatusChoice.SUSPENDED:
        return False
    return True


def _get_wiki_user(request: HttpRequest) -> User | None:
    user_id = request.session.get(WIKI_SESSION_KEY)
    if not user_id:
        return None
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return None
    if not _is_wiki_admin(user):
        return None
    return user


def wiki_admin_required(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    @wraps(view)
    def wrapped(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        user = _get_wiki_user(request)
        if user is None:
            request.session.pop(WIKI_SESSION_KEY, None)
            login_url = reverse("wiki-login")
            return redirect(f"{login_url}?next={request.path}")
        request.wiki_user = user
        return view(request, *args, **kwargs)

    return wrapped


def _sidebar_context(request: HttpRequest) -> dict[str, object]:
    pages = list_pages()
    return {
        "wiki_user": getattr(request, "wiki_user", None),
        "grouped_pages": group_pages(pages),
        "query": request.GET.get("q", "").strip(),
    }


@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest) -> HttpResponse:
    if _get_wiki_user(request) is not None:
        return redirect("wiki-index")

    error = ""
    next_url = request.POST.get("next") or request.GET.get("next") or reverse("wiki-index")
    if not next_url.startswith("/wiki/"):
        next_url = reverse("wiki-index")

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip()
        password = request.POST.get("password") or ""
        user = authenticate(request, username=email, password=password)
        if _is_wiki_admin(user):
            request.session.cycle_key()
            request.session[WIKI_SESSION_KEY] = user.id
            return redirect(next_url)
        error = LOGIN_ERROR_MESSAGE

    return render(
        request,
        "wiki/login.html",
        {"error": error, "next": next_url},
    )


@require_http_methods(["POST", "GET"])
def logout_view(request: HttpRequest) -> HttpResponse:
    request.session.flush()
    return redirect("wiki-login")


@wiki_admin_required
@require_http_methods(["GET"])
def index_view(request: HttpRequest) -> HttpResponse:
    query = (request.GET.get("q") or "").strip()
    context = _sidebar_context(request)
    context["hits"] = search_pages(query) if query else []
    return render(request, "wiki/index.html", context)


@wiki_admin_required
@require_http_methods(["GET"])
def page_view(request: HttpRequest, slug: str) -> HttpResponse:
    page = load_page(slug)
    if page is None:
        return render(
            request,
            "wiki/not_found.html",
            {**_sidebar_context(request), "slug": slug},
            status=404,
        )
    context = _sidebar_context(request)
    context["page"] = page
    context["current_slug"] = slug
    return render(request, "wiki/page.html", context)
