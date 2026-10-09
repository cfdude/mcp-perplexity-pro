"""Alembic environment, driven programmatically by ``storage.migrate``.

The runner hands in an open synchronous connection (already inside a ``BEGIN IMMEDIATE``
transaction) and a list to record applied revisions in, through ``config.attributes``. There is
no ``alembic.ini`` and no database URL here on purpose.
"""

from alembic import context

config = context.config
connection = config.attributes["connection"]
applied: list[str] = config.attributes.setdefault("applied", [])


def _record(*, step, **_kwargs) -> None:
    applied.append(step.up_revision.revision)


context.configure(
    connection=connection,
    target_metadata=None,
    transactional_ddl=True,
    transaction_per_migration=False,
    on_version_apply=_record,
)
with context.begin_transaction():
    context.run_migrations()
