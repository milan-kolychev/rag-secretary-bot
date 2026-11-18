"""Migration URL comes from the same settings as API/worker; never log credentials."""

from alembic import context
from sqlalchemy import create_engine, pool

from core.config import PersistenceSettings
from core.db import Base

url = PersistenceSettings().database_url
if not url:
    raise RuntimeError("DATABASE_URL is required")

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
