"""Usta tool names use dots (file.read); Anthropic/OpenAI wire names allow only [a-zA-Z0-9_-]."""


def encode(name: str) -> str:
    # A "_" next to "." would make decode() misread the run of underscores
    # ("a_.b" -> "a___b" -> "a._b"), so such names are refused too.
    if "__" in name or "_." in name or "._" in name:
        raise ValueError(f"tool name {name!r} must not contain '__' or '_' adjacent to '.'")
    return name.replace(".", "__")


def decode(wire_name: str) -> str:
    return wire_name.replace("__", ".")
