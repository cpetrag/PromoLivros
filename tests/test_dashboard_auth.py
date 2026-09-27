import unittest

from promo_livros.dashboard_auth import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_wrong_password_returns_no_token(self) -> None:
        store = SessionStore()
        self.assertIsNone(store.login("ana", "errada", "ana", "certa"))
        self.assertIsNone(store.login("errada", "certa", "ana", "certa"))
        self.assertFalse(store.valid(None))
        self.assertFalse(store.valid("token-inventado"))

    def test_accented_password_is_rejected_not_crashed(self) -> None:
        store = SessionStore()
        self.assertIsNone(store.login("ana", "coração", "ana", "certa"))
        self.assertIsNotNone(store.login("ana", "coração", "ana", "coração"))

    def test_right_password_is_accepted_until_forget(self) -> None:
        store = SessionStore()
        token = store.login("ana", "certa", "ana", "certa")
        self.assertIsNotNone(token)
        assert token is not None
        self.assertTrue(store.valid(token))
        store.forget(token)
        self.assertFalse(store.valid(token))


if __name__ == "__main__":
    unittest.main()
