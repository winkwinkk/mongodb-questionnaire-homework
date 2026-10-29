import unittest
from unittest.mock import patch

from app import create_app


class PageTests(unittest.TestCase):
    def setUp(self):
        with patch.dict("os.environ", {"FLASK_SECRET_KEY": "page-test-only"}):
            self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_public_auth_pages_and_safe_return_path(self):
        self.assertEqual(self.client.get("/").status_code, 302)
        for page in ("/login", "/register"):
            result = self.client.get(page + "?next=//evil.example/path")
            self.assertEqual(result.status_code, 200)
            self.assertIn(b'data-next="/dashboard"', result.data)
        result = self.client.get("/login?next=/survey/abc")
        self.assertIn(b'data-next="/survey/abc"', result.data)

    def test_pages_require_login_and_render_after_login(self):
        paths = ["/dashboard", "/surveys/new", "/surveys/abc/edit", "/survey/abc", "/surveys/abc/statistics"]
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 302)
        with self.client.session_transaction() as session:
            session["user_id"] = "000000000000000000000001"
        for path in paths:
            with self.subTest(path=path):
                result = self.client.get(path)
                self.assertEqual(result.status_code, 200)
                self.assertIn('问序'.encode(), result.data)

    def test_assets_and_health_are_available(self):
        for path in ("/static/css/app.css", "/static/js/app.js", "/api/health"):
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
