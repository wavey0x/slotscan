import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy.dialects import postgresql

from app.repositories.source_cache import SourceCacheRepository


ADDRESS = "0x" + "11" * 20
CODE_HASH = "0x" + "aa" * 32


class SourceCacheRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_upsert_uses_application_utc_for_expiry_timestamp(self):
        session = AsyncMock()
        repository = SourceCacheRepository(session)
        checked_at = datetime(2026, 7, 21, 14, 0, 0)

        with patch(
            "app.repositories.source_cache.datetime",
        ) as datetime_mock:
            datetime_mock.utcnow.return_value = checked_at
            await repository.save_not_found(1, ADDRESS, CODE_HASH)

        statement = session.execute.await_args.args[0]
        compiled = statement.compile(dialect=postgresql.dialect())

        self.assertNotIn("now()", str(compiled).lower())
        self.assertGreaterEqual(
            list(compiled.params.values()).count(checked_at),
            1,
        )
        session.commit.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
