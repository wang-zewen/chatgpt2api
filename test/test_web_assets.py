import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import api.support as api_support
from api.app import create_app


class WebAssetsTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        web_dist = Path(tmp.name)
        (web_dist / "image").mkdir()
        (web_dist / "_next" / "static" / "chunks").mkdir(parents=True)
        (web_dist / "index.html").write_text("<html>home</html>", encoding="utf-8")
        (web_dist / "image" / "index.html").write_text("<html>image</html>", encoding="utf-8")
        (web_dist / "image" / "index.txt").write_text("rsc", encoding="utf-8")
        (web_dist / "_next" / "static" / "chunks" / "app.js").write_text("js", encoding="utf-8")
        patcher = mock.patch.object(api_support, "WEB_DIST_DIR", web_dist)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(create_app())

    def test_page_routes_serve_html_without_long_cache(self) -> None:
        for path in ("/image", "/image/", "/unknown-page"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertEqual(response.headers["cache-control"], "no-cache", path)
        self.assertIn("image", self.client.get("/image").text)

    def test_rsc_payload_is_revalidated(self) -> None:
        response = self.client.get("/image/index.txt?_rsc=abc")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-cache")

    def test_hashed_static_assets_are_immutable(self) -> None:
        response = self.client.get("/_next/static/chunks/app.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "public, max-age=31536000, immutable")

    def test_missing_static_asset_is_404(self) -> None:
        self.assertEqual(self.client.get("/_next/static/chunks/missing.js").status_code, 404)


if __name__ == "__main__":
    unittest.main()
