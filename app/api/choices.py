"""Django TextChoices → OpenAPI enum.

ModelSchema 필드는 `choices`가 있으면 /api/docs에 enum·한글 라벨이 자동으로 나온다.
엔드포인트 description에 클래스 코드를 복붙하지 않는다.

FilterSchema·일반 Schema처럼 모델에서 안 올라오는 필드는 `enum_field`를 쓴다.
"""

from __future__ import annotations

from typing import Any, Iterable, Literal

from django.db.models import Field as DjangoField
from django.db.models import TextChoices
from ninja import Field
from pydantic.fields import FieldInfo

_PATCHED = False

ChoicesLike = type[TextChoices] | dict[str, str] | Iterable[tuple[Any, Any]]


def choice_pairs(choices: ChoicesLike) -> list[tuple[Any, str]]:
    if isinstance(choices, dict):
        return list(choices.items())
    if isinstance(choices, type) and issubclass(choices, TextChoices):
        return [(value, str(label)) for value, label in choices.choices]
    pairs: list[tuple[Any, str]] = []
    for item in choices:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        value, label = item[0], item[1]
        if isinstance(label, (list, tuple)):
            for nested in label:
                if isinstance(nested, (list, tuple)) and len(nested) >= 2:
                    pairs.append((nested[0], str(nested[1])))
            continue
        pairs.append((value, str(label)))
    return pairs


def choice_description(title: str, choices: ChoicesLike) -> str:
    items = " · ".join(
        f"`{value}` {label}" for value, label in choice_pairs(choices)
    )
    return f"{title}. {items}"


def choice_literal(choices: ChoicesLike) -> Any:
    values = tuple(str(value) for value, _ in choice_pairs(choices))
    return Literal.__getitem__(values)


def enum_field(
    title: str,
    choices: ChoicesLike,
    default: Any = ...,
    **kwargs: Any,
) -> Any:
    extra = dict(kwargs.pop("json_schema_extra", None) or {})
    extra["enum"] = [value for value, _ in choice_pairs(choices)]
    return Field(
        default,
        description=choice_description(title, choices),
        json_schema_extra=extra,
        **kwargs,
    )


def django_field_choices(field: DjangoField) -> list[tuple[Any, str]] | None:
    if getattr(field, "is_relation", False):
        return None
    choices = getattr(field, "choices", None)
    if callable(choices):
        choices = choices()
    if not choices:
        return None
    pairs = choice_pairs(choices)
    return pairs or None


def apply_django_choices(
    field: DjangoField,
    python_type: Any,
    field_info: FieldInfo,
) -> tuple[Any, FieldInfo]:
    """타입은 str로 두고 OpenAPI enum·description만 채운다."""
    pairs = django_field_choices(field)
    if not pairs:
        return python_type, field_info

    title = str(field.help_text or field.verbose_name or field.name)
    description = choice_description(title, pairs)
    extra = field_info.json_schema_extra
    extra_dict = dict(extra) if isinstance(extra, dict) else {}
    extra_dict["enum"] = [value for value, _ in pairs]
    enriched = FieldInfo.merge_field_infos(
        field_info,
        FieldInfo(description=description, json_schema_extra=extra_dict),
    )
    return python_type, enriched


def _wrap_get_schema_field(original):
    def wrapped(field, *, depth: int = 0, optional: bool = False):
        python_type, field_info = original(field, depth=depth, optional=optional)
        return apply_django_choices(field, python_type, field_info)

    return wrapped


def install_choice_schema_patch() -> None:
    """ninja ModelSchema가 Django choices를 OpenAPI enum으로 내보내게 한다."""
    global _PATCHED
    if _PATCHED:
        return

    import ninja.orm.factory as ninja_factory
    import ninja.orm.fields as ninja_fields

    wrapped = _wrap_get_schema_field(ninja_fields.get_schema_field)
    ninja_fields.get_schema_field = wrapped
    ninja_factory.get_schema_field = wrapped
    _PATCHED = True
