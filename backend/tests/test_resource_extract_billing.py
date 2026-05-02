import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.resource_task_service import _compute_points_from_cost
from services.task_job_service import billing_rule_for_task_type, serialize_task_job


def test_resource_extract_points_round_up_without_service_fee():
    assert _compute_points_from_cost(Decimal("0")) == 0
    assert _compute_points_from_cost(Decimal("0.01")) == 1
    assert _compute_points_from_cost(Decimal("0.10")) == 1
    assert _compute_points_from_cost(Decimal("0.11")) == 2


def test_task_job_billing_rule_for_resource_extract():
    assert billing_rule_for_task_type("resource.extract") == "if actual_cost_cny > 0 then ceil(actual_cost_cny / 0.1) else 0"

    job = SimpleNamespace(
        task_id="task-1",
        task_type="resource.extract",
        queue_name="resource",
        status="succeeded",
        progress=100,
        stage="syncing_resources",
        message="done",
        provider="deepseek",
        priority=100,
        task_category="resource",
        ownership_mode="project",
        scope_type="script",
        scope_id=1,
        script_id=1,
        episode_id=None,
        membership_source=None,
        membership_plan_id=None,
        membership_plan_name=None,
        membership_subject_type=None,
        membership_subject_id=None,
        concurrency_limit=None,
        actual_cost_cny=0.11,
        charged_points=2,
        actual_points=2,
        points_status="deducted",
        upstream_task_id=None,
        callback_token=None,
        next_poll_at=None,
        poll_attempts=0,
        callback_received_at=None,
        generation_record_id=None,
        payload_json="{}",
        result_json="{}",
        error_code=None,
        error_message=None,
        cancel_requested_at=None,
        retry_count=0,
        max_retries=1,
        worker_id=None,
        scheduled_at=None,
        started_at=None,
        finished_at=None,
        heartbeat_at=None,
        lease_expires_at=None,
        created_at=None,
        updated_at=None,
        billing_detail_json="[]",
    )

    data = serialize_task_job(job)
    assert data["billing"]["billing_rule"] == "if actual_cost_cny > 0 then ceil(actual_cost_cny / 0.1) else 0"
