from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.config.database import Base
from app.config.settings import settings
from app.models import (  # noqa: F401
    IdentityProvider,
    PlayerPosition,
    PlayerProfile,
    User,
    UserIdentity,
)

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Only manage tables defined on our SQLAlchemy models (ignore PostGIS/extensions).
_MANAGED_TABLES = set(target_metadata.tables.keys())


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table":
        return name in _MANAGED_TABLES
    if type_ in {"index", "unique_constraint", "foreign_key_constraint"}:
        table = getattr(object, "table", None)
        if table is not None:
            return table.name in _MANAGED_TABLES
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
