"""Settings read from environment variables (and .env if present). TRIVENI_ prefix."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    falkordb_host: str
    falkordb_port: int
    falkordb_username: str | None
    falkordb_password: str | None
    falkordb_ssl: bool
    default_tenant: str


def get_settings() -> Settings:
    return Settings(
        falkordb_host=os.getenv("TRIVENI_FALKORDB_HOST", "localhost"),
        falkordb_port=int(os.getenv("TRIVENI_FALKORDB_PORT", "6379")),
        falkordb_username=os.getenv("TRIVENI_FALKORDB_USERNAME") or None,
        falkordb_password=os.getenv("TRIVENI_FALKORDB_PASSWORD") or None,
        falkordb_ssl=_bool(os.getenv("TRIVENI_FALKORDB_SSL")),
        default_tenant=os.getenv("TRIVENI_DEFAULT_TENANT", "acme"),
    )
