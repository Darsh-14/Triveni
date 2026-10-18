"""One shared FalkorDB connection for the process. Graph selection lives in tenant.py."""
import os
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
        # fail fast: an unreachable database must surface as an error in seconds, not hang every request
        socket_connect_timeout=float(os.getenv("TRIVENI_FALKORDB_CONNECT_TIMEOUT", "5")),
        socket_timeout=float(os.getenv("TRIVENI_FALKORDB_TIMEOUT", "120")),  # seeding a whole graph is one long write
    )


def ping() -> bool:
    """True when FalkorDB answers. Used by tests and the API health check."""
    try:
        return bool(get_db().connection.ping())
    except Exception:
        return False
