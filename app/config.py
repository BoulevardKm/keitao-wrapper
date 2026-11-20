import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    keitaro_base_url: str
    keitaro_api_key: str
    keitaro_domain: str
    keitaro_group: str
    keitaro_source: str
    keitaro_safe_url: str
    database_url: str

    @property
    def templates_dir(self) -> Path:
        return ROOT / "app" / "templates"

    @property
    def static_dir(self) -> Path:
        return ROOT / "app" / "static"


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    return Settings(
        keitaro_base_url=_env("KEITARO_BASE_URL", "https://in.posdk.xyz"),
        keitaro_api_key=_env("KEITARO_API_KEY"),
        keitaro_domain=_env("KEITARO_DOMAIN", "kylovoa.com"),
        keitaro_group=_env("KEITARO_GROUP", "FORTESTS"),
        keitaro_source=_env("KEITARO_SOURCE", "FORTESTS"),
        keitaro_safe_url=_env("KEITARO_SAFE_URL", "https://google.com"),
        database_url=_env("DATABASE_URL", "sqlite:///./data/app.db"),
    )


settings = load_settings()
