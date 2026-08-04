from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CloudflareDeploymentContracts(unittest.TestCase):
    def test_wrangler_binds_current_native_entrypoint_resources(self) -> None:
        config = (ROOT / "cloudflare" / "native-worker" / "wrangler.toml").read_text(encoding="utf-8")

        self.assertIn('name = "aiusage-api"', config)
        self.assertIn('main = "src/index.ts"', config)
        self.assertIn("workers_dev = false", config)
        self.assertIn('AIUSAGE_BACKEND_MODE = "native_d1_production"', config)
        self.assertIn('pattern = "aiusage.chunbai.com/*"', config)
        self.assertIn('binding = "AIUSAGE_DB"', config)
        self.assertIn('database_name = "aiusage-prod-db"', config)
        self.assertIn('database_id = "be19e4de-4fa3-446c-8028-0d31ff0bb9f2"', config)
        self.assertIn('binding = "AIUSAGE_BACKUPS"', config)
        self.assertIn('bucket_name = "aiusage-backups"', config)
        self.assertIn('crons = ["17 19 * * *", "23 18 1 * *"]', config)
        self.assertFalse((ROOT / "wrangler.toml").exists())
        self.assertFalse((ROOT / "cloudflare" / "aiusage-api-worker.js").exists())

    def test_pages_is_not_the_current_dashboard_success_path(self) -> None:
        package_json = (ROOT / "package.json").read_text(encoding="utf-8")
        root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
        readme = (ROOT / "cloudflare" / "README.md").read_text(encoding="utf-8")

        self.assertIn("wrangler deploy", package_json)
        self.assertIn("cf:worker:deploy", package_json)
        self.assertIn("aiusage.chunbai.com/*", readme)
        self.assertIn("Cloudflare Native Worker + D1", readme)
        self.assertIn("VPN2 旧 AI Usage 后端", readme)
        self.assertIn("Dashboard 页面由 Native Worker 直接提供", readme)
        self.assertNotIn("cf:pages:deploy", package_json)
        self.assertIn("生产入口已经切到 Cloudflare Worker + D1", root_readme)
        self.assertIn("VPN2 旧后端不再承载 AI Usage 读写链路", root_readme)
        self.assertIn("不要用 `curl -I`", readme)
        self.assertIn("--resolve aiusage.chunbai.com:443:<Cloudflare IP>", readme)
        for asset in ["index.html", "dashboard.css", "dashboard.js", "login.html"]:
            self.assertTrue((ROOT / "cloudflare" / "native-worker" / "static" / asset).exists())

    def test_operations_handoff_points_to_actual_ops_workspace(self) -> None:
        handoff = (ROOT / "cloudflare" / "OPERATIONS_HANDOFF.md").read_text(encoding="utf-8")

        self.assertIn("/Users/wangzhipeng/Documents/ops", handoff)
        self.assertIn("codex exec --cd /Users/wangzhipeng/Documents/ops --skip-git-repo-check", handoff)
        self.assertNotIn("/Users/wangzhipeng/Documents/cloud-flare", handoff)
        self.assertIn("不要读取或输出 `.env`", handoff)
        self.assertIn("不要用 `curl -I`", handoff)
        self.assertIn("curl -D - -o /dev/null", handoff)
        self.assertIn("未登录 /static/* 预期可以是 401", handoff)
        self.assertIn("带 session cookie 后 /static/dashboard.js 和 /static/dashboard.css 必须是 200", handoff)

if __name__ == "__main__":
    unittest.main()
