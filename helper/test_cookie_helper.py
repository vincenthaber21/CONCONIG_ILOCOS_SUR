import unittest
from unittest.mock import patch

from helper.cookie_helper import set_secure_cookie


class _DummyResponse:
    def __init__(self):
        self.calls = []

    def set_cookie(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})


class TestSetSecureCookie(unittest.TestCase):
    def test_sets_secure_and_httponly_when_explicit(self):
        response = _DummyResponse()

        set_secure_cookie(
            response,
            "sessionid",
            "abc123",
            max_age=60,
            secure=True,
            httponly=True,
        )

        self.assertEqual(len(response.calls), 1)
        call = response.calls[0]
        self.assertEqual(call["args"][0], "sessionid")
        self.assertEqual(call["args"][1], "abc123")
        self.assertTrue(call["kwargs"]["secure"])
        self.assertTrue(call["kwargs"]["httponly"])

    def test_defaults_secure_from_production_env(self):
        response = _DummyResponse()
        with patch.dict("os.environ", {"PRODUCTION": "true"}, clear=False):
            set_secure_cookie(response, "k", "v")

        call = response.calls[0]
        self.assertTrue(call["kwargs"]["secure"])
        self.assertTrue(call["kwargs"]["httponly"])
        self.assertEqual(call["kwargs"]["samesite"], "Strict")


if __name__ == "__main__":
    unittest.main()
