from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "common"

    def ready(self) -> None:
        from api.choices import install_choice_schema_patch

        install_choice_schema_patch()


# admin.autodiscover가 ModelSchema를 만들기 전에 패치해야 한다.
from api.choices import install_choice_schema_patch as _install_choice_schema_patch

_install_choice_schema_patch()
