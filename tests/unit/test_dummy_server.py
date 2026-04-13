import pytest
import httpx


@pytest.mark.asyncio
async def test_dummy_search_server_responds(dummy_search_server):
    async with httpx.AsyncClient() as client:
        resp = await client.get(dummy_search_server + "python")
    assert resp.status_code == 200
    assert "Result" in resp.text


@pytest.mark.asyncio
async def test_dummy_page_responds(dummy_search_server):
    base = dummy_search_server.replace("/search?q=", "")
    async with httpx.AsyncClient() as client:
        resp = await client.get(base + "/page/1")
    assert resp.status_code == 200
    assert "Test Content 1" in resp.text
