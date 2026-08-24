import unittest

from app.db import engine


class DatabasePoolTests(unittest.TestCase):
    def test_connections_are_checked_before_pool_checkout(self):
        self.assertTrue(engine.sync_engine.pool._pre_ping)


if __name__ == "__main__":
    unittest.main()
