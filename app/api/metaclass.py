from ninja.schema import Schema
from ninja import ModelSchema
from typing import no_type_check
from ninja.orm.metaclass import MetaConf

from api.factory import create_schema
from ninja.schema import ResolverMetaclass

from pydantic import field_validator

_is_modelschema_class_defined = False


class CustomModelSchemaMetaclass(ResolverMetaclass):
    @no_type_check
    def __new__(
        mcs,
        name: str,
        bases: tuple,
        namespace: dict,
        **kwargs,
    ):
        cls = super().__new__(
            mcs,
            name,
            bases,
            namespace,
            **kwargs,
        )

        for base in reversed(bases):
            if (
                _is_modelschema_class_defined
                and issubclass(base, CustomModelSchema)
                and base == CustomModelSchema
            ):
                meta_conf = MetaConf.from_schema_class(name, namespace)

                custom_fields = []
                annotations = namespace.get("__annotations__", {})
                for attr_name, type in annotations.items():
                    if attr_name.startswith("_"):
                        continue
                    default = namespace.get(attr_name, ...)
                    custom_fields.append((attr_name, type, default))

                choice_validators = {}
                for field in meta_conf.model._meta.get_fields():
                    if hasattr(field, "choices") and field.choices:
                        field_name = field.name
                        choices_set = {choice[0] for choice in field.choices}

                        def make_validator(field_name, choices_set):
                            def validate_choice(value):
                                if value not in choices_set:
                                    raise ValueError(
                                        f"{field_name} must be one of {choices_set}"
                                    )
                                return value

                            return validate_choice

                        validate_choice = make_validator(field_name, choices_set)
                        choice_validators["validate_" + field_name] = field_validator(
                            field_name, check_fields=False
                        )(validate_choice)

                model_schema = create_schema(
                    meta_conf.model,
                    name=name,
                    fields=meta_conf.fields,
                    exclude=meta_conf.exclude,
                    optional_fields=meta_conf.fields_optional,
                    custom_fields=custom_fields,
                    base_class=cls,
                    choice_validators=choice_validators,
                )
                model_schema.__doc__ = cls.__doc__
                return model_schema

        return cls


class CustomModelSchema(Schema, metaclass=CustomModelSchemaMetaclass):
    pass


_is_modelschema_class_defined = True
