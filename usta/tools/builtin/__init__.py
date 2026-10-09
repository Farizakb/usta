from usta.tools.builtin.files import FILE_LIST, FILE_READ, FILE_SEARCH, FILE_WRITE
from usta.tools.builtin.todo import TODO
from usta.tools.registry import Tool


def builtin_tools() -> list[Tool]:
    """Tools that need nothing but the workspace. code_exec and skill.load are built in
    usta.app.wiring because they need the sandbox and the skill set."""
    return [FILE_LIST, FILE_READ, FILE_SEARCH, FILE_WRITE, TODO]
