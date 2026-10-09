"""A cancelled unit of work still returns its connection to the pool.

FastMCP and anyio cancel with a level-triggered scope: every await inside a cancelled scope
raises again, so a ``rollback()`` or ``close()`` awaited bare in the cleanup is itself cut short
and the connection stays checked out until the garbage collector finds it (an SAWarning). A
client that drops a request mid-write is how this happens in the real server."""

import anyio
import pytest
from sqlalchemy import text

from mcp_perplexity_pro.storage.session import unit_of_work


@pytest.mark.parametrize("write", [True, False])
async def test_a_unit_of_work_cancelled_mid_block_returns_its_connection(storage_engine, write):
    with anyio.CancelScope() as scope:
        async with unit_of_work(storage_engine, write=write) as session:
            await session.execute(text("SELECT 1"))
            scope.cancel()
            await anyio.sleep(5)  # cancelled here; the cleanup that follows is cancelled too
    for _ in range(100):  # the shielded cleanup may finish just after the scope exits
        if storage_engine.pool.checkedout() == 0:
            break
        await anyio.sleep(0.01)
    assert storage_engine.pool.checkedout() == 0
