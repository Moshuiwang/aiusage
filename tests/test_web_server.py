from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import unittest
from http.cookies import SimpleCookie
import urllib.request
import urllib.error
import urllib.parse

from ai_usage_widget.limits import LimitWindow
from ai_usage_widget.server import start_test_server
from ai_usage_widget.storage_sqlite import write_limit_windows


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class TestWebServerSummary(unittest.TestCase):
    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        self.out_fd, self.out_path = tempfile.mkstemp(suffix=".json")
        self.token = "admin-secret-token"

        # 动态获取一个本地空闲端口
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()

        # 在后台线程启动测试 Web Server
        self.server_thread, self.httpd = start_test_server(
            host="127.0.0.1",
            port=self.port,
            db_path=self.db_path,
            latest_path=self.out_path,
            token=self.token,
            timezone="Asia/Shanghai"
        )
        # 稍等服务器启动完毕
        time.sleep(0.5)

        self.valid_payload = {
            "schema_version": 1,
            "source_id": "mac-local",
            "host": "macbook-pro",
            "os_user": "wangzhipeng",
            "platform": "darwin",
            "timezone": "Asia/Shanghai",
            "observed_at": "2026-06-01T10:40:00+08:00",
            "collection_window": "daily",
            "usage_daily": [
                {
                    "agent": "claude",
                    "period": "2026-06-01",
                    "inputTokens": 1200,
                    "outputTokens": 800,
                    "totalTokens": 2000
                }
            ]
        }

    def tearDown(self) -> None:
        # 关闭服务器
        self.httpd.shutdown()
        self.server_thread.join()
        self.httpd.server_close()

        os.close(self.db_fd)
        os.close(self.out_fd)
        for p in [self.db_path, self.out_path]:
            if os.path.exists(p):
                os.remove(p)

    def test_get_summary_empty_state(self) -> None:
        """测试初始无数据时，请求 /api/summary 返回包含空 summary 的合法快照"""
        url = f"http://127.0.0.1:{self.port}/api/summary"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode("utf-8"))
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["summary"]["total_tokens"], 0)

    def test_summary_requires_auth(self) -> None:
        """测试 /api/summary 未登录时拒绝读取"""
        url = f"http://127.0.0.1:{self.port}/api/summary"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url)
        self.assertEqual(ctx.exception.code, 401)

    def test_health_requires_auth_and_returns_low_cost_status(self) -> None:
        health_url = f"http://127.0.0.1:{self.port}/api/health"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(health_url)
        self.assertEqual(ctx.exception.code, 401)

        req = urllib.request.Request(health_url, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode("utf-8"))

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["database"]["path"], self.db_path)
        self.assertGreaterEqual(data["database"]["size_bytes"], 0)
        self.assertIn("source_status", data)
        self.assertIn("generated_at", data)

    def test_ingest_auth_failure(self) -> None:
        """测试推送时未提供 token 或提供错误 token 导致 401 失败"""
        url = f"http://127.0.0.1:{self.port}/ingest"
        req_data = json.dumps(self.valid_payload).encode("utf-8")

        # 1. 错误 Token
        req = urllib.request.Request(
            url, data=req_data, headers={"Authorization": "Bearer bad-token", "Content-Type": "application/json"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 401)

        # 2. 缺失 Token
        req_no_auth = urllib.request.Request(
            url, data=req_data, headers={"Content-Type": "application/json"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req_no_auth)
        self.assertEqual(ctx.exception.code, 401)

    def test_ingest_accepts_rotated_token_specs(self) -> None:
        self.httpd.shutdown()
        self.server_thread.join()
        self.httpd.server_close()
        self.server_thread, self.httpd = start_test_server(
            host="127.0.0.1",
            port=self.port,
            db_path=self.db_path,
            latest_path=self.out_path,
            token=self.token,
            token_specs="ai:rotated-token",
            timezone="Asia/Shanghai",
        )
        time.sleep(0.5)

        url = f"http://127.0.0.1:{self.port}/ingest"
        req = urllib.request.Request(
            url,
            data=json.dumps(self.valid_payload).encode("utf-8"),
            headers={"Authorization": "Bearer rotated-token", "Content-Type": "application/json"},
        )

        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)

    def test_ingest_success_and_query_summary(self) -> None:
        """测试正常流程：推送成功后，查询 summary 能够获取累加的 token 和设备状态"""
        url_ingest = f"http://127.0.0.1:{self.port}/ingest"
        req_data = json.dumps(self.valid_payload).encode("utf-8")

        # 1. 发送 Ingest 推送
        req = urllib.request.Request(
            url_ingest,
            data=req_data,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 200)
            resp_body = json.loads(response.read().decode("utf-8"))
            self.assertEqual(resp_body["status"], "accepted")

        # 2. 请求 /api/summary 检验数据汇总和 source_status
        url_summary = f"http://127.0.0.1:{self.port}/api/summary?date=2026-06-01"
        req_summary = urllib.request.Request(url_summary, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req_summary) as response:
            self.assertEqual(response.status, 200)
            summary_data = json.loads(response.read().decode("utf-8"))

            self.assertEqual(summary_data["summary"]["total_tokens"], 2000)
            self.assertEqual(summary_data["summary"]["input_tokens"], 1200)

            # 校验 source_status 列表
            status_list = summary_data["source_status"]
            self.assertEqual(len(status_list), 1)
            self.assertEqual(status_list[0]["source_id"], "mac-local")
            self.assertEqual(status_list[0]["status"], "ok")

    def test_summary_returns_limits_from_canonical_store(self) -> None:
        write_limit_windows(
            self.db_path,
            [
                LimitWindow(
                    provider="codex",
                    window="week",
                    used_percent=44.0,
                    remaining_percent=56.0,
                    reset_at="2026-06-08T00:00:00+08:00",
                    window_duration_minutes=10080,
                    observed_at="2026-06-01T10:45:00+08:00",
                    source_type="runtime_api",
                    confidence="observed",
                    status="ok",
                )
            ],
            seen_at="2026-06-01T10:45:00+08:00",
        )

        url_summary = f"http://127.0.0.1:{self.port}/api/summary?date=2026-06-01"
        req_summary = urllib.request.Request(url_summary, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req_summary) as response:
            self.assertEqual(response.status, 200)
            summary_data = json.loads(response.read().decode("utf-8"))

        self.assertEqual(summary_data["summary"]["total_tokens"], 0)
        self.assertEqual(len(summary_data["limits"]), 1)
        self.assertEqual(summary_data["limits"][0]["provider"], "codex")
        self.assertEqual(summary_data["limits"][0]["window"], "week")
        self.assertEqual(summary_data["limits"][0]["reset_at"], "2026-06-08T00:00:00+08:00")

    def test_summary_period_query_uses_period_parameter(self) -> None:
        """测试 /api/summary?period=week 返回 period 字段和范围聚合结构"""
        url_ingest = f"http://127.0.0.1:{self.port}/ingest"
        for period, tokens in [("2026-06-01", 2000), ("2026-06-02", 3000)]:
            payload = dict(self.valid_payload)
            payload["observed_at"] = f"{period}T10:40:00+08:00"
            payload["usage_daily"] = [{
                "agent": "claude",
                "period": period,
                "inputTokens": tokens,
                "outputTokens": 0,
                "totalTokens": tokens,
            }]
            req = urllib.request.Request(
                url_ingest,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as response:
                self.assertEqual(response.status, 200)

        url_summary = f"http://127.0.0.1:{self.port}/api/summary?date=2026-06-02&period=week"
        req_summary = urllib.request.Request(url_summary, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req_summary) as response:
            self.assertEqual(response.status, 200)
            summary_data = json.loads(response.read().decode("utf-8"))

        self.assertEqual(summary_data["summary"]["period"], "week")
        self.assertEqual(summary_data["summary"]["start_date"], "2026-05-27")
        self.assertEqual(summary_data["summary"]["end_date"], "2026-06-02")
        self.assertEqual(summary_data["summary"]["total_tokens"], 5000)
        self.assertEqual(summary_data["trend"]["axis"], [
            "2026-05-27",
            "2026-05-28",
            "2026-05-29",
            "2026-05-30",
            "2026-05-31",
            "2026-06-01",
            "2026-06-02",
        ])

    def test_summary_groups_machine_users_and_filters_user_report(self) -> None:
        """同一台 Linux 机器多 OS 用户上报后，机器下列出用户，用户报表复用 summary schema"""
        url_ingest = f"http://127.0.0.1:{self.port}/ingest"
        payloads = [
            ("linux-dev-wang", "linux-dev", "wang", 2000),
            ("linux-dev-li", "linux-dev", "li", 3500),
        ]
        for source_id, host, os_user, tokens in payloads:
            payload = dict(self.valid_payload)
            payload["source_id"] = source_id
            payload["host"] = host
            payload["os_user"] = os_user
            payload["platform"] = "linux"
            payload["observed_at"] = "2026-06-01T10:40:00+08:00"
            payload["usage_daily"] = [{
                "agent": "claude",
                "period": "2026-06-01",
                "inputTokens": tokens,
                "outputTokens": 0,
                "totalTokens": tokens,
            }]
            req = urllib.request.Request(
                url_ingest,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as response:
                self.assertEqual(response.status, 200)

        url_summary = f"http://127.0.0.1:{self.port}/api/summary?date=2026-06-01"
        req_summary = urllib.request.Request(url_summary, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req_summary) as response:
            summary_data = json.loads(response.read().decode("utf-8"))

        linux_group = next(row for row in summary_data["groups"]["by_machine"] if row["name"] == "linux-dev")
        self.assertEqual(linux_group["total_tokens"], 5500)
        self.assertEqual(
            [(user["account"], user["total_tokens"]) for user in linux_group["users"]],
            [("li", 3500), ("wang", 2000)],
        )

        filtered_url = (
            f"http://127.0.0.1:{self.port}/api/summary?"
            f"date=2026-06-01&machine=linux-dev&account=wang"
        )
        filtered_req = urllib.request.Request(filtered_url, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(filtered_req) as response:
            filtered_data = json.loads(response.read().decode("utf-8"))

        self.assertEqual(filtered_data["summary"]["total_tokens"], 2000)
        self.assertEqual(filtered_data["summary"]["machine"], "linux-dev")
        self.assertEqual(filtered_data["summary"]["account"], "wang")
        self.assertEqual(filtered_data["groups"]["by_machine"][0]["users"][0]["account"], "wang")
        self.assertEqual([source["source_id"] for source in filtered_data["source_status"]], ["linux-dev-wang"])

    def test_get_dashboard_html(self) -> None:
        """测试请求 / 和 /dashboard 能返回 index.html 内容"""
        for path in ["/", "/dashboard"]:
            url = f"http://127.0.0.1:{self.port}{path}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"})
            with urllib.request.urlopen(req) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get("Content-Type"), "text/html; charset=utf-8")
                html_content = response.read().decode("utf-8")
                self.assertIn("AI Usage Observability", html_content)
                self.assertIn('data-dashboard="wight"', html_content)
                self.assertIn("dashboard.css", html_content)
                self.assertIn("dashboard.js", html_content)

    def test_dashboard_static_assets(self) -> None:
        """测试 dashboard 的 CSS/JS 静态资源可加载"""
        cases = [
            ("/static/dashboard.css", "text/css; charset=utf-8", "hero-total"),
            ("/static/dashboard.js", "application/javascript; charset=utf-8", "periodSelector"),
        ]
        for path, content_type, marker in cases:
            with self.subTest(path=path):
                url = f"http://127.0.0.1:{self.port}{path}"
                req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"})
                with urllib.request.urlopen(req) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers.get("Content-Type"), content_type)
                    self.assertIn(marker, response.read().decode("utf-8"))

    def test_dashboard_limits_static_hooks(self) -> None:
        dashboard_url = f"http://127.0.0.1:{self.port}/dashboard"
        dashboard_req = urllib.request.Request(dashboard_url, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(dashboard_req) as response:
            html_content = response.read().decode("utf-8")

        js_url = f"http://127.0.0.1:{self.port}/static/dashboard.js"
        js_req = urllib.request.Request(js_url, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(js_req) as response:
            js_content = response.read().decode("utf-8")

        self.assertIn('id="limitsSection"', html_content)
        self.assertIn("renderLimits", js_content)

    def test_login_sets_cookie_for_dashboard(self) -> None:
        """测试浏览器登录后能用 cookie 访问 Dashboard"""
        login_url = f"http://127.0.0.1:{self.port}/login"
        body = urllib.parse.urlencode({"token": self.token}).encode("utf-8")
        req = urllib.request.Request(
            login_url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        opener = urllib.request.build_opener(NoRedirectHandler)
        try:
            opener.open(req)
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 303)
            cookie = SimpleCookie(exc.headers["Set-Cookie"])

        session_cookie = cookie["ai_usage_session"].value
        dashboard_url = f"http://127.0.0.1:{self.port}/dashboard"
        dashboard_req = urllib.request.Request(
            dashboard_url,
            headers={"Cookie": f"ai_usage_session={session_cookie}"},
        )
        with urllib.request.urlopen(dashboard_req) as response:
            self.assertEqual(response.status, 200)
            html_content = response.read().decode("utf-8")
            self.assertIn("AI Usage Observability", html_content)
