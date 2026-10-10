"""Small Pydantic-v2 compatibility surface for SpotiFLAC on Android.

Pydantic v2 depends on the Rust ``pydantic-core`` extension, for which there
is no Chaquopy Android wheel. SpotiFLAC uses a deliberately small part of the
API for two data containers. This module implements that exact surface in pure
Python so the upstream SpotiFLAC package can run in the embedded interpreter.
It is not a general Pydantic replacement.
"""

from __future__ import annotations

import copy
import inspect
import types
from dataclasses import dataclass
from typing import Any, get_args, get_origin


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidationInfo:
    field_name: str


class _Undefined:
    pass


_UNDEFINED = _Undefined()


class _FieldInfo:
    def __init__(self, default: Any = _UNDEFINED, default_factory=None, **_kwargs):
        self.default = default
        self.default_factory = default_factory

    def value(self):
        if self.default_factory is not None:
            return self.default_factory()
        if self.default is _UNDEFINED:
            return _UNDEFINED
        return copy.deepcopy(self.default)


def Field(default: Any = _UNDEFINED, *, default_factory=None, **kwargs):
    return _FieldInfo(default, default_factory, **kwargs)


def field_validator(*fields: str, mode: str = "after", **_kwargs):
    def decorate(value):
        function = value.__func__ if isinstance(value, classmethod) else value
        function.__android_pydantic_field_validator__ = (tuple(fields), mode)
        return value

    return decorate


def model_validator(*, mode: str = "after", **_kwargs):
    def decorate(value):
        function = value.__func__ if isinstance(value, classmethod) else value
        function.__android_pydantic_model_validator__ = mode
        return value

    return decorate


def _all_annotations(cls) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for base in reversed(cls.__mro__):
        fields.update(getattr(base, "__annotations__", {}))
    return {name: kind for name, kind in fields.items() if not name.startswith("_")}


def _unwrap(value):
    return value.__func__ if isinstance(value, classmethod) else value


class _ModelMeta(type):
    def __new__(mcls, name, bases, namespace):
        cls = super().__new__(mcls, name, bases, namespace)
        field_validators = []
        model_validators = []
        for base in bases:
            field_validators.extend(getattr(base, "__field_validators__", []))
            model_validators.extend(getattr(base, "__model_validators__", []))
        for attr_name, value in namespace.items():
            function = _unwrap(value)
            marker = getattr(function, "__android_pydantic_field_validator__", None)
            if marker:
                field_validators.append((attr_name, marker[0], marker[1]))
            model_mode = getattr(function, "__android_pydantic_model_validator__", None)
            if model_mode:
                model_validators.append((attr_name, model_mode))
        cls.__field_validators__ = field_validators
        cls.__model_validators__ = model_validators
        return cls


class BaseModel(metaclass=_ModelMeta):
    model_config: dict[str, Any] = {}

    def __init__(self, **values):
        annotations = _all_annotations(type(self))
        try:
            for name in annotations:
                if name == "model_config":
                    continue
                if name in values:
                    value = values[name]
                else:
                    declared = getattr(type(self), name, _UNDEFINED)
                    value = declared.value() if isinstance(declared, _FieldInfo) else copy.deepcopy(declared)
                if value is _UNDEFINED:
                    raise ValueError(f"Missing required field: {name}")
                for method_name, fields, mode in self.__field_validators__:
                    if name not in fields or mode != "before":
                        continue
                    method = getattr(type(self), method_name)
                    if len(inspect.signature(method).parameters) >= 2:
                        value = method(value, ValidationInfo(name))
                    else:
                        value = method(value)
                setattr(self, name, value)

            if getattr(type(self), "model_config", {}).get("extra") != "ignore":
                for name, value in values.items():
                    if name not in annotations:
                        setattr(self, name, value)

            for method_name, mode in self.__model_validators__:
                if mode == "after":
                    result = getattr(self, method_name)()
                    if result is not None and result is not self:
                        self.__dict__.update(result.__dict__)
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError(str(exc)) from exc

    @classmethod
    def model_validate(cls, value):
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict):
            raise ValidationError(f"Expected mapping for {cls.__name__}")
        return cls(**value)

    def model_dump(self, *, exclude_none: bool = False, **_kwargs) -> dict[str, Any]:
        def unpack(value):
            if isinstance(value, BaseModel):
                return value.model_dump(exclude_none=exclude_none)
            if isinstance(value, list):
                return [unpack(item) for item in value]
            if isinstance(value, dict):
                return {key: unpack(item) for key, item in value.items()}
            return value

        result = {}
        for name in _all_annotations(type(self)):
            if name == "model_config" or not hasattr(self, name):
                continue
            value = getattr(self, name)
            if exclude_none and value is None:
                continue
            result[name] = unpack(value)
        return result

    def model_copy(self, *, update: dict[str, Any] | None = None, deep: bool = False):
        values = self.model_dump()
        if deep:
            values = copy.deepcopy(values)
        values.update(update or {})
        return type(self)(**values)


__all__ = [
    "BaseModel",
    "Field",
    "ValidationError",
    "ValidationInfo",
    "field_validator",
    "model_validator",
]
