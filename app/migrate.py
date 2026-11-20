"""Apply Alembic migrations. Run from the project root: python -m app.migrate"""

from alembic import command
from alembic.config import Config

from app.config import ROOT
from app.database import ensure_sqlite_parent
from app.config import settings


def main() -> None:
    ensure_sqlite_parent(settings.database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    command.upgrade(config, "head")


if __name__ == "__main__":
    main()
