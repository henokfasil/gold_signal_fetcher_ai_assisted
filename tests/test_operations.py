import unittest
from pathlib import Path


class OperationsConfigTests(unittest.TestCase):
    def test_plaintext_8502_is_redirect_only(self):
        config = Path("ops/nginx/gold-signal-fetcher.conf").read_text()
        servers = config.split("\nserver {")
        self.assertGreaterEqual(len(servers), 4)

        legacy_http = servers[1]
        self.assertIn("listen 8502;", legacy_http)
        self.assertIn("return 301 https://187.55.229.4$request_uri;", legacy_http)
        self.assertNotIn("proxy_pass", legacy_http)
        self.assertNotIn("auth_basic", legacy_http)

        tls = servers[3]
        self.assertIn("listen 443 ssl;", tls)
        self.assertIn('auth_basic "Gold Signal Research";', tls)
        self.assertIn("proxy_pass http://127.0.0.1:8510;", tls)


if __name__ == "__main__":
    unittest.main()
