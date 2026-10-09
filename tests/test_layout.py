import importlib

import pytest

LAYER_MODULES = [
    "usta.core",
    "usta.ports",
    "usta.engines.own",
    "usta.models",
    "usta.tools.builtin",
    "usta.store",
    "usta.app",
    "usta.worker",
    "usta.cli",
]


@pytest.mark.parametrize("module", LAYER_MODULES)
def test_layer_module_imports(module: str) -> None:
    importlib.import_module(module)
