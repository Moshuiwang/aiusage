from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CloudflareDeploymentContracts(unittest.TestCase):
    def test_wrangler_binds_current_native_entrypoint_resources(self) -> None:
        config = (ROOT / "wrangler.toml").read_text(encoding="utf-8")

        self.assertIn('name = "aiusage-api"', config)
        self.assertIn('main = "cloudflare/aiusage-api-worker.js"', config)
        self.assertIn('ENVIRONMENT = "development"', config)
        self.assertIn(
            'ORIGIN_BASE_URL = "https://aiusage-native-staging.chunbai.workers.dev"',
            config,
        )
        self.assertNotIn("vpn2.chunbai.com", config)
        self.assertIn('pattern = "aiusage.chunbai.com/*"', config)
        self.assertNotIn('pattern = "aiusage.chunbai.com/api/*"', config)
        self.assertNotIn('pattern = "aiusage.chunbai.com/ingest"', config)
        self.assertNotIn('pattern = "aiusage.chunbai.com/ingest-limits"', config)
        self.assertIn('binding = "AIUSAGE_DB"', config)
        self.assertIn('database_name = "aiusage-dev-db"', config)
        self.assertIn('database_id = "35ba085b-f437-41a1-b3c4-9bba30ec4723"', config)
        self.assertIn('binding = "AIUSAGE_KV"', config)
        self.assertIn('id = "ce0c08082b034abcb2012b91eed9991a"', config)
        self.assertIn('binding = "AIUSAGE_ASSETS"', config)
        self.assertIn('bucket_name = "aiusage-dev-assets"', config)

    def test_worker_proxies_web_api_and_ingest_paths_without_secret_literals(self) -> None:
        worker = (ROOT / "cloudflare" / "aiusage-api-worker.js").read_text(encoding="utf-8")

        self.assertIn("ORIGIN_BASE_URL", worker)
        for path_marker in [
            "WEB_PATH_MARKERS",
            "api/mobile/summary",
            "api/summary",
            "api/health",
            "static/dashboard.js",
            "static/dashboard.css",
            "login",
            "dashboard",
            "ingest-limits",
        ]:
            with self.subTest(path_marker=path_marker):
                self.assertIn(path_marker, worker)
        self.assertIn('pathname === "/"', worker)
        self.assertIn('pathname === "/dashboard"', worker)
        self.assertIn('pathname === "/login"', worker)
        self.assertIn('pathname.startsWith("/static/")', worker)
        self.assertIn('pathname.startsWith("/api/")', worker)
        self.assertIn('pathname === "/ingest"', worker)
        self.assertIn('pathname === "/ingest-limits"', worker)
        self.assertIn("Cloudflare Worker only handles AI Usage web, API, and ingest paths.", worker)
        self.assertIn("await request.arrayBuffer()", worker)
        self.assertNotIn("request.body", worker)
        self.assertIn("buildProxyInit", worker)
        self.assertIn("Cache-Control", worker)
        self.assertIn("no-store", worker)
        self.assertIn("Vary", worker)
        self.assertIn("Authorization", worker)
        self.assertIn("Cookie", worker)
        self.assertNotRegex(worker, re.compile(r"[a-f0-9]{40,}", re.IGNORECASE))
        self.assertNotIn("AI_USAGE_INGEST_TOKEN =", worker)
        self.assertNotIn("AI_USAGE_INGEST_TOKENS =", worker)

    def test_pages_is_not_the_current_dashboard_success_path(self) -> None:
        package_json = (ROOT / "package.json").read_text(encoding="utf-8")
        root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
        readme = (ROOT / "cloudflare" / "README.md").read_text(encoding="utf-8")
        package = (
            ROOT
            / "docs"
            / "task-packages"
            / "v2"
            / "TP-V2-083-cloudflare-entrypoint-migration.md"
        ).read_text(encoding="utf-8")

        self.assertIn("wrangler deploy", package_json)
        self.assertIn("cf:worker:deploy", package_json)
        self.assertIn("aiusage.chunbai.com/*", readme)
        self.assertIn("Cloudflare Native Worker + D1", readme)
        self.assertIn("VPN2 旧 AI Usage 后端已经下线", readme)
        self.assertIn("Pages 静态化不是当前用户入口", readme)
        self.assertIn("生产入口已经切到 Cloudflare Worker + D1", root_readme)
        self.assertIn("VPN2 旧后端不再承载 AI Usage 读写链路", root_readme)
        self.assertIn("不要用 `curl -I`", readme)
        self.assertIn("--resolve aiusage.chunbai.com:443:<Cloudflare IP>", readme)
        self.assertIn("Worker 统一入口回源旧服务", package)
        self.assertIn("Pages 静态化不作为本轮成功标准", package)
        self.assertIn("Status: completed", package)
        self.assertIn("用户浏览器验收已确认", package)
        for asset in ["index.html", "dashboard.css", "dashboard.js", "login.html"]:
            self.assertTrue((ROOT / "src" / "ai_usage_widget" / "static" / asset).exists())

    def test_operations_handoff_points_to_cloud_flare_sibling_codex_cli(self) -> None:
        handoff = (ROOT / "cloudflare" / "OPERATIONS_HANDOFF.md").read_text(encoding="utf-8")

        self.assertIn("/Users/wangzhipeng/Documents/cloud-flare", handoff)
        self.assertIn("codex exec --cd /Users/wangzhipeng/Documents/cloud-flare --skip-git-repo-check", handoff)
        self.assertIn("不要读取或输出 .env", handoff)
        self.assertIn("不要用 `curl -I`", handoff)
        self.assertIn("curl -D - -o /dev/null", handoff)
        self.assertIn("未登录 /static/* 预期可以是 401", handoff)
        self.assertIn("带 session cookie 后 /static/dashboard.js 和 /static/dashboard.css 必须是 200", handoff)

    def test_cloudflare_task_package_is_indexed(self) -> None:
        index = (ROOT / "docs" / "task-packages" / "v2" / "INDEX.md").read_text(encoding="utf-8")
        package = (
            ROOT
            / "docs"
            / "task-packages"
            / "v2"
            / "TP-V2-083-cloudflare-entrypoint-migration.md"
        ).read_text(encoding="utf-8")

        self.assertIn("TP-V2-083", index)
        self.assertIn("Cloudflare Entrypoint Migration", package)
        self.assertIn("aiusage.chunbai.com", package)


if __name__ == "__main__":
    unittest.main()
