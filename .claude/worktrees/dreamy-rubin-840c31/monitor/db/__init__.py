"""
monitor.db 包入口（目录 monitor/db/）。

为何需要本文件：
  Python 不允许在 monitor/ 下同时以常规方式并存「db.py 模块」与「db/ 包」并都叫 monitor.db。
  因此以本包为唯一导入入口，在导入时把同级的 monitor/db.py 单文件模块挂到 sys.modules["monitor.db"]。

加载顺序（`import monitor.db` 时）：
  1. 解释器加载本 __init__.py；
  2. 构造 db.py 对应的模块对象，并设置 __path__ 指向本目录 monitor/db/，使 monitor.db 同时具备「单文件实现」与「子包挂载点」能力
     （否则 monitor.db 仅是普通 module，无法 import monitor.db.queries）；
  3. 执行 db.py，注册 sys.modules["monitor.db"]，并把其中公开名合并到本包 globals；
  4. 再显式加载 monitor/db/connection.py、db_core.py，将连接与共享常量注入命名空间（覆盖/对齐 db.py 中的同名符号）。

关于 monitor/db/queries/：
  不将各 queries 子模块中的函数「平铺」注入 monitor.db 顶层（会与 db.py 中已有 API 重名或难以维护）；
  需要时使用 `import monitor.db.queries.<模块>` 或 `from monitor.db.queries.<模块> import ...`。

使用约定：业务代码统一 `import monitor.db`；子包通过上述 __path__ 正常解析。
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
# 使 monitor.db 表现为包：可 import monitor.db.queries.*（见模块文档说明）
_mod.__path__ = [_db_dir]
_spec.submodule_search_locations = [_db_dir]

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
