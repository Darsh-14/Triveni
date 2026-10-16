"""One shared FalkorDB connection for the process. Graph selection lives in tenant.py."""
from functools import lru_cache

from falkordb import FalkorDB

from backend.app.config import get_settings


@lru_cache(maxsize=1)
def get_db() -> FalkorDB:
    s = get_settings()
    return FalkorDB(
        host=s.falkordb_host,
        port=s.falkordb_port,
        username=s.falkordb_username,
        password=s.falkordb_password,
        ssl=s.falkordb_ssl,
    )


def ping() -> bool:
    """True when FalkorDB answers. Used by tests and the API health check."""
    try:
        return bool(get_db().connection.ping())
    except Exception:
        return False
