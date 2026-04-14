"""
monitor.db — Backward-compatibility shim.
"""
import importlib.machinery
import importlib.util
import os
import sys
from types import ModuleType

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_db_py_path = os.path.join(_parent, "db.py")
_db_dir = os.path.join(_parent, "db")

_loader = importlib.machinery.SourceFileLoader("monitor.db", _db_py_path)
_spec = importlib.util.spec_from_loader("monitor.db", _loader, origin=_db_py_path)
_mod = _loader.create_module(_spec)
if _mod is None:
    _mod = ModuleType(_spec.name)
_mod.__spec__ = _spec
_mod.__loader__ = _loader
_mod.__file__ = _db_py_path

sys.modules["monitor._db"] = _mod
sys.modules["monitor.db"] = _mod
_loader.exec_module(_mod)
globals().update({name: getattr(_mod, name) for name in dir(_mod)})


def _load_submodule(name: str, path: str):
    ldr = importlib.machinery.SourceFileLoader(name, path)
    sp = importlib.util.spec_from_loader(name, ldr, origin=path)
    m = ldr.create_module(sp)
    if m is None:
        m = ModuleType(sp.name)
    m.__spec__ = sp
    m.__loader__ = ldr
    m.__file__ = path
    sys.modules[name] = m
    ldr.exec_module(m)
    return m


_conn = _load_submodule("monitor.db.connection", os.path.join(_db_dir, "connection.py"))
for _n in ("_DATA_DIR", "_DB_PATH", "_CONFIG_PATH", "_SCHEMA_PATH",
           "_set_db_path", "_set_data_dir", "_reset_paths", "get_connection"):
    globals()[_n] = getattr(_conn, _n)

_core = _load_submodule("monitor.db.db_core", os.path.join(_db_dir, "db_core.py"))
for _n in ("_UNSET", "_iso_future"):
    globals()[_n] = getattr(_core, _n)
