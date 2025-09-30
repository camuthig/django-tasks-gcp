from traceback import format_exception
from typing import Any


def get_module_path(val: Any) -> str:
    return f"{val.__module__}.{val.__qualname__}"


def get_exception_traceback(exc: BaseException) -> str:
    return "".join(format_exception(exc))