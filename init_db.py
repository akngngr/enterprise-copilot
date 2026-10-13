from alembic import command
from alembic.config import Config


def init_db() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")


if __name__ == "__main__":
    init_db()
