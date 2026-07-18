from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents/skills/loop-executor/scripts/merge_gate.py"


def load_gate_module():
    spec = importlib.util.spec_from_file_location("loop_merge_gate", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def allowed_context() -> dict:
    return {
        "loop_engineering": "2.2.0",
        "approval_status": "approved",
        "merge_pr": "when_no_open_p0_p1",
        "merge_method": "squash",
        "repository_allows_method": True,
        "forbidden": ["push_default_branch", "force_push"],
        "requested_revision": 3,
        "yaml_revision": 3,
        "approval_comment_revision": 3,
        "plan_identity_match": True,
        "approval_comment_scoped": True,
        "approver_authorized": True,
        "human_attestation_available": True,
        "plan_digest_match": True,
        "required_issues": [29, 30, 32],
        "live_recursive_issues": [29, 30, 32],
        "contract_digest_keys": [29, 30, 32],
        "contract_digests_match": True,
        "all_work_complete": True,
        "pr_head": "abc123",
        "clean_head": True,
        "validation_head": "abc123",
        "required_review_rounds": 1,
        "review_heads": ["abc123"],
        "ci_head": "abc123",
        "risk": "standard",
        "high_checkpoint_head": None,
        "no_open_p0_p1": True,
        "p0_p1_findings": [],
        "pr_ready": True,
        "base_ref_name": "main",
        "base_branch": "main",
        "mergeable": True,
        "branch_rules_satisfied": True,
        "required_checks_satisfied": True,
        "required_approvals_satisfied": True,
        "synchronous_merge": True,
        "merge_queue_active": False,
        "auto_merge_active": False,
        "expected_head_supported": True,
    }


class LoopMergeGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_gate_module()

    def test_complete_standard_context_is_allowed(self) -> None:
        decision = self.module.evaluate_gate(allowed_context())
        self.assertTrue(decision.allowed, decision.errors)

    def test_each_security_boundary_fails_closed(self) -> None:
        cases = {
            "manual": ("merge_pr", "manual"),
            "forbidden_merge": ("forbidden", ["merge_pr"]),
            "old_requested_revision": ("requested_revision", 2),
            "cross_plan_comment": ("approval_comment_scoped", False),
            "unauthorized_approver": ("approver_authorized", False),
            "missing_human_attestation": ("human_attestation_available", False),
            "plan_digest_changed": ("plan_digest_match", False),
            "recursive_issue_added": ("live_recursive_issues", [29, 30, 31, 32]),
            "contract_digest_missing": ("contract_digest_keys", [29, 30]),
            "contract_body_changed": ("contract_digests_match", False),
            "head_changed": ("ci_head", "new-head"),
            "open_p1": ("no_open_p0_p1", False),
            "retargeted_base": ("base_ref_name", "release"),
            "queue": ("merge_queue_active", True),
            "auto_merge": ("auto_merge_active", True),
            "async_merge": ("synchronous_merge", False),
            "no_expected_head": ("expected_head_supported", False),
            "unknown_mergeability": ("mergeable", None),
        }
        for name, (key, value) in cases.items():
            with self.subTest(name=name):
                context = allowed_context()
                context[key] = value
                decision = self.module.evaluate_gate(context)
                self.assertFalse(decision.allowed)
                self.assertTrue(decision.errors)

    def test_high_requires_checkpoint_for_exact_latest_head(self) -> None:
        context = allowed_context()
        context["risk"] = "high"
        context["required_review_rounds"] = 2
        context["review_heads"] = [context["pr_head"], context["pr_head"]]

        self.assertFalse(self.module.evaluate_gate(context).allowed)

        context["high_checkpoint_head"] = context["pr_head"]
        self.assertTrue(self.module.evaluate_gate(context).allowed)

        context["pr_head"] = "new-head"
        self.assertFalse(self.module.evaluate_gate(context).allowed)

    def test_high_human_authorized_one_round_exception_is_explicit(self) -> None:
        context = allowed_context()
        context["risk"] = "high"
        context["required_review_rounds"] = 1
        context["review_heads"] = [context["pr_head"]]
        context["high_checkpoint_head"] = context["pr_head"]

        self.assertTrue(self.module.evaluate_gate(context).allowed)

        context["required_review_rounds"] = 0
        context["review_heads"] = []
        self.assertFalse(self.module.evaluate_gate(context).allowed)

    def test_light_does_not_invent_review_evidence(self) -> None:
        context = allowed_context()
        context["risk"] = "light"
        context["required_review_rounds"] = 0
        context["review_heads"] = []

        self.assertTrue(self.module.evaluate_gate(context).allowed)

        context["review_heads"] = [context["pr_head"]]
        self.assertFalse(self.module.evaluate_gate(context).allowed)

    def test_missing_or_unknown_fields_fail_closed(self) -> None:
        context = allowed_context()
        del context["plan_digest_match"]
        self.assertFalse(self.module.evaluate_gate(context).allowed)

    def test_contract_identity_and_approval_are_strict(self) -> None:
        cases = {
            "draft": ("approval_status", "draft"),
            "unsupported_version": ("loop_engineering", "2.3.0"),
            "null_revision": ("requested_revision", None),
            "boolean_revision": ("yaml_revision", True),
            "zero_revision": ("approval_comment_revision", 0),
            "unknown_base": ("base_ref_name", None),
            "empty_base": ("base_branch", ""),
        }
        for name, (key, value) in cases.items():
            with self.subTest(name=name):
                context = allowed_context()
                if "revision" in name:
                    context["requested_revision"] = value
                    context["yaml_revision"] = value
                    context["approval_comment_revision"] = value
                else:
                    context[key] = value
                self.assertFalse(self.module.evaluate_gate(context).allowed)

    def test_issue_contract_sets_must_be_nonempty_unique_positive_integers(self) -> None:
        invalid_sets = ([], [29, 29], [0, 29], [True, 29], ["29", 30])
        for values in invalid_sets:
            with self.subTest(values=values):
                context = allowed_context()
                context["required_issues"] = values
                context["live_recursive_issues"] = values
                context["contract_digest_keys"] = values
                self.assertFalse(self.module.evaluate_gate(context).allowed)

    def test_forbidden_must_be_a_unique_string_list(self) -> None:
        for value in ({}, "force_push", ["force_push", "force_push"], [1]):
            with self.subTest(value=value):
                context = allowed_context()
                context["forbidden"] = value
                self.assertFalse(self.module.evaluate_gate(context).allowed)

    def test_cli_rejects_duplicate_json_keys(self) -> None:
        payload = json.dumps(allowed_context(), separators=(",", ":"))
        payload = payload.replace(
            '"no_open_p0_p1":true',
            '"no_open_p0_p1":false,"no_open_p0_p1":true',
        )
        completed = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=payload,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertFalse(json.loads(completed.stdout)["allowed"])

    def test_each_p0_p1_finding_requires_structured_resolution_on_latest_head(self) -> None:
        resolved = {
            "id": "REV-P1-1",
            "severity": "P1",
            "reviewed_head": "abc123",
            "disposition": "fixed",
            "evidence_url": "https://github.com/Moshuiwang/aiusage/issues/32#issuecomment-1",
            "adjudicator": "reviewer-1",
        }
        context = allowed_context()
        context["p0_p1_findings"] = [resolved]
        self.assertTrue(self.module.evaluate_gate(context).allowed)

        mutations = {
            "missing_id": {**resolved, "id": ""},
            "wrong_severity": {**resolved, "severity": "P2"},
            "old_head": {**resolved, "reviewed_head": "old-head"},
            "accepted_risk": {**resolved, "disposition": "accepted"},
            "missing_url": {**resolved, "evidence_url": ""},
            "missing_adjudicator": {**resolved, "adjudicator": ""},
        }
        for name, finding in mutations.items():
            with self.subTest(name=name):
                context = allowed_context()
                context["p0_p1_findings"] = [finding]
                self.assertFalse(self.module.evaluate_gate(context).allowed)


if __name__ == "__main__":
    unittest.main()
