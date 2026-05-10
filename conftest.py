"""Shared test helpers."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPTS_DIR = Path(__file__).parent / "scripts"


def load_script(name: str) -> ModuleType:
    """Load a module from scripts/ by name, registering it in sys.modules.

    Registration is required before exec_module so that ``@dataclass`` under
    ``from __future__ import annotations`` can resolve ``cls.__module__``.
    """
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
