from usta.tools.builtin.files import FILE_READ
from usta.tools.builtin.todo import TODO
from usta.tools.registry import Tool


def builtin_tools() -> list[Tool]:
    return [FILE_READ, TODO]
