from app.core.valkey import valkey_client


async def test_the_client_reaches_the_test_sets_valkey():
    client = valkey_client()
    try:
        assert await client.ping() is True
    finally:
        await client.aclose()
