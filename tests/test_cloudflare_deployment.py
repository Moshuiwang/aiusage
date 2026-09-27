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
        self.assertNotIn("cf:pages:deploy", package_json)
        self.assertIn("生产入口已经切到 Cloudflare Worker + D1", root_readme)
        self.assertIn("VPN2 旧后端不再承载 AI Usage 读写链路", root_readme)
        self.assertIn("不要用 `curl -I`", readme)
        self.assertIn("--resolve aiusage.chunbai.com:443:<Cloudflare IP>", readme)
        # #199：网页看板本身（`/`、`/dashboard`、登录页、静态资源）整体废弃，
        # 不再落地为 static/ 目录下的文件；`/api/summary` 是否删除另议。
        self.assertFalse((ROOT / "cloudflare" / "native-worker" / "static").exists())

    def test_operations_handoff_points_to_actual_ops_workspace(self) -> None:
        handoff = (ROOT / "cloudflare" / "OPERATIONS_HANDOFF.md").read_text(encoding="utf-8")

        self.assertIn("/Users/wangzhipeng/Documents/ops", handoff)
        self.assertIn("codex exec --cd /Users/wangzhipeng/Documents/ops --skip-git-repo-check", handoff)
        self.assertNotIn("/Users/wangzhipeng/Documents/cloud-flare", handoff)
        self.assertIn("不要读取或输出 `.env`", handoff)
        self.assertIn("不要用 `curl -I`", handoff)
        self.assertIn("curl -D - -o /dev/null", handoff)
        # #199：网页看板本身（`/`、`/dashboard`、登录页、`/static/*`）整体废弃，
        # smoke 清单不再有专门的静态资源 / session cookie 步骤。
        self.assertIn("网页看板", handoff)
        self.assertNotIn("session cookie", handoff)
        self.assertNotIn("dashboard.js", handoff)

if __name__ == "__main__":
    unittest.main()
