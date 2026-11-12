from types import SimpleNamespace

import pytest

from admin import MasterOnly


@pytest.mark.asyncio
async def test_admin_router_filter_rejects_everyone_except_master():
    check = MasterOnly()
    event = SimpleNamespace(from_user=SimpleNamespace(id=100))
    assert await check(event, master_id=100)
    event.from_user.id = 200
    assert not await check(event, master_id=100)
