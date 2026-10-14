"""数据库子包。

导出：
- 异步新接口：get_db, init_async_db, dispose_engine, Base, get_engine
- 同步旧接口（向后兼容）：get_conn, init_db（来自 legacy.py，SQLite 同步）

旧代码 `from app.db import get_conn` 不需要修改。
"""
from app.db.base import (  # noqa: F401
    Base,
    dispose_engine,
    get_db,
    get_engine,
    get_session_factory,
    init_async_db,
)
from app.db.legacy import DB_PATH, get_conn, init_db  # noqa: F401
