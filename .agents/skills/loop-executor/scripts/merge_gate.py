#!/usr/bin/env python3
"""Fail-closed evaluator for Loop Executor conditional PR merge evidence."""

from __future__ import annotations

from dataclasses import dataclass
import json
import sys
from typing import Any


REQUIRED_FIELDS = {
    "loop_engineering",
    "approval_status",
    "merge_pr",
    "merge_method",
    "repository_allows_method",
    "forbidden",
    "requested_revision",
    "yaml_revision",
    "approval_comment_revision",
    "plan_identity_match",
    "approval_comment_scoped",
    "approver_authorized",
    "human_attestation_available",
    "plan_digest_match",
    "required_issues",
    "live_recursive_issues",
    "contract_digest_keys",
    "contract_digests_match",
    "all_work_complete",
    "pr_head",
    "clean_head",
    "validation_head",
    "required_review_rounds",
    "review_heads",
    "ci_head",
    "risk",
    "high_checkpoint_head",
    "no_open_p0_p1",
    "p0_p1_findings",
    "pr_ready",
    "base_ref_name",
    "base_branch",
    "mergeable",
    "branch_rules_satisfied",
    "required_checks_satisfied",
    "required_approvals_satisfied",
    "synchronous_merge",
    "merge_queue_active",
    "auto_merge_active",
    "expected_head_supported",
}


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    errors: tuple[str, ...]


def evaluate_gate(context: dict[str, Any]) -> GateDecision:
    errors: list[str] = []

    missing = sorted(REQUIRED_FIELDS - context.keys())
    if missing:
        return GateDecision(False, tuple(f"missing:{field}" for field in missing))
    unknown = sorted(context.keys() - REQUIRED_FIELDS)
    if unknown:
        return GateDecision(False, tuple(f"unknown:{field}" for field in unknown))

    if context["loop_engineering"] != "2.2.0":
        errors.append("unsupported_loop_engineering")
    if context["approval_status"] != "approved":
        errors.append("plan_not_approved")

    if context["merge_pr"] != "when_no_open_p0_p1":
        errors.append("merge_not_authorized")
    if context["merge_method"] not in {"squash", "merge", "rebase"}:
        errors.append("invalid_merge_method")
    if context["repository_allows_method"] is not True:
        errors.append("merge_method_not_allowed")
    forbidden = context["forbidden"]
    if (
        not isinstance(forbidden, list)
        or any(not isinstance(item, str) or not item for item in forbidden)
        or len(forbidden) != len(set(forbidden))
    ):
        errors.append("invalid_forbidden")
    elif "merge_pr" in forbidden:
        errors.append("merge_forbidden")

    revision_values = (
        context["requested_revision"],
        context["yaml_revision"],
        context["approval_comment_revision"],
    )
    if any(type(value) is not int or value <= 0 for value in revision_values):
        errors.append("invalid_revision")
    elif len(set(revision_values)) != 1:
        errors.append("revision_mismatch")

    required_true = {
        "plan_identity_match": "plan_identity_mismatch",
        "approval_comment_scoped": "approval_comment_out_of_scope",
        "approver_authorized": "approver_not_authorized",
        "human_attestation_available": "human_attestation_missing",
        "plan_digest_match": "plan_digest_mismatch",
        "contract_digests_match": "contract_digest_mismatch",
        "all_work_complete": "work_incomplete",
        "clean_head": "head_not_clean",
        "no_open_p0_p1": "open_p0_p1",
        "pr_ready": "pr_not_ready",
        "branch_rules_satisfied": "branch_rules_unsatisfied",
        "required_checks_satisfied": "required_checks_unsatisfied",
        "required_approvals_satisfied": "required_approvals_unsatisfied",
        "synchronous_merge": "merge_not_synchronous",
        "expected_head_supported": "expected_head_not_supported",
    }
    for field, error in required_true.items():
        if context[field] is not True:
            errors.append(error)

    issue_sets = (
        context["required_issues"],
        context["live_recursive_issues"],
        context["contract_digest_keys"],
    )
    if any(
        not isinstance(values, list)
        or not values
        or any(type(value) is not int or value <= 0 for value in values)
        or len(values) != len(set(values))
        for values in issue_sets
    ):
        errors.append("invalid_issue_sets")
    else:
        required, live, digest_keys = (sorted(values) for values in issue_sets)
        if required != live:
            errors.append("recursive_issue_graph_changed")
        if required != digest_keys:
            errors.append("contract_digest_coverage_changed")

    head = context["pr_head"]
    if not isinstance(head, str) or not head:
        errors.append("invalid_pr_head")
    elif context["validation_head"] != head or context["ci_head"] != head:
        errors.append("evidence_head_mismatch")

    if context["risk"] not in {"light", "standard", "high"}:
        errors.append("invalid_risk")
    required_review_rounds = context["required_review_rounds"]
    review_heads = context["review_heads"]
    if type(required_review_rounds) is not int:
        errors.append("invalid_required_review_rounds")
    elif context["risk"] == "light" and required_review_rounds != 0:
        errors.append("invalid_light_review_rounds")
    elif context["risk"] == "standard" and required_review_rounds != 1:
        errors.append("invalid_standard_review_rounds")
    elif context["risk"] == "high" and required_review_rounds not in {1, 2}:
        errors.append("invalid_high_review_rounds")
    if (
        not isinstance(review_heads, list)
        or type(required_review_rounds) is not int
        or len(review_heads) != required_review_rounds
        or any(review_head != head for review_head in review_heads)
    ):
        errors.append("review_evidence_mismatch")
    if context["risk"] == "high" and context["high_checkpoint_head"] != head:
        errors.append("high_checkpoint_head_mismatch")

    findings = context["p0_p1_findings"]
    finding_fields = {
        "id",
        "severity",
        "reviewed_head",
        "disposition",
        "evidence_url",
        "adjudicator",
    }
    if not isinstance(findings, list):
        errors.append("invalid_p0_p1_findings")
    else:
        finding_ids: set[str] = set()
        for finding in findings:
            if not isinstance(finding, dict) or set(finding) != finding_fields:
                errors.append("invalid_p0_p1_finding_shape")
                continue
            finding_id = finding["id"]
            if not isinstance(finding_id, str) or not finding_id or finding_id in finding_ids:
                errors.append("invalid_p0_p1_finding_id")
            else:
                finding_ids.add(finding_id)
            if finding["severity"] not in {"P0", "P1"}:
                errors.append("invalid_p0_p1_severity")
            if finding["reviewed_head"] != head:
                errors.append("p0_p1_finding_head_mismatch")
            if finding["disposition"] not in {"fixed", "disproven"}:
                errors.append("p0_p1_finding_unresolved")
            evidence_url = finding["evidence_url"]
            if not isinstance(evidence_url, str) or not evidence_url.startswith("https://"):
                errors.append("invalid_p0_p1_evidence_url")
            adjudicator = finding["adjudicator"]
            if not isinstance(adjudicator, str) or not adjudicator:
                errors.append("invalid_p0_p1_adjudicator")

    if (
        not isinstance(context["base_ref_name"], str)
        or not context["base_ref_name"]
        or not isinstance(context["base_branch"], str)
        or not context["base_branch"]
    ):
        errors.append("invalid_base_branch")
    elif context["base_ref_name"] != context["base_branch"]:
        errors.append("base_branch_mismatch")
    if context["mergeable"] is not True:
        errors.append("pr_not_mergeable")
    if context["merge_queue_active"] is not False:
        errors.append("merge_queue_active")
    if context["auto_merge_active"] is not False:
        errors.append("auto_merge_active")

    return GateDecision(not errors, tuple(errors))


def main() -> int:
    try:
        def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON key: {key}")
                result[key] = value
            return result

        payload = json.load(sys.stdin, object_pairs_hook=reject_duplicate_keys)
        if not isinstance(payload, dict):
            raise ValueError("input must be a JSON object")
        decision = evaluate_gate(payload)
    except Exception as exc:  # fail closed for malformed or unknown evidence
        print(json.dumps({"allowed": False, "errors": [f"invalid_input:{exc}"]}))
        return 2

    print(json.dumps({"allowed": decision.allowed, "errors": decision.errors}))
    return 0 if decision.allowed else 2


if __name__ == "__main__":
    raise SystemExit(main())
