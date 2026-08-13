"""Load protocol-only modules without importing Home Assistant integration setup."""

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).parents[1]
PACKAGE = "custom_components.kaisai_khx"

custom = types.ModuleType("custom_components")
custom.__path__ = [str(ROOT / "custom_components")]
sys.modules.setdefault("custom_components", custom)
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "custom_components" / "kaisai_khx")]
sys.modules.setdefault(PACKAGE, package)

for name in ("profile", "api"):
    full_name = f"{PACKAGE}.{name}"
    spec = importlib.util.spec_from_file_location(full_name, ROOT / "custom_components" / "kaisai_khx" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
