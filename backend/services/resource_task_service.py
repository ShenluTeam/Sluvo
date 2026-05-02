from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING
from typing import Any, Dict

from core.config import settings
from database import engine
from models import Team, User
from services.billing_service import deduct_inspiration_points
from services.resource_extraction_service import extract_script_assets_into_shared_resources
from services.shared_resource_generation_service import run_shared_resource_generation
from services.task_registry import resource_extract_tasks
from services.task_job_service import (
    TASK_STATUS_CANCELLED,
    get_task_job,
    is_task_cancel_requested,
    mark_task_job_failed,
    mark_task_job_succeeded,
    update_task_job,
)
from services.generation_record_service import _complete_record_success, _mark_failed
from services.deepseek_model_policy import calculate_deepseek_v4_flash_usage_cost_cny
from sqlmodel import Session


POINTS_UNIT_CNY = Decimal("0.1")
POINTS_STATUS_FREE = "free"
POINTS_STATUS_DEDUCTED = "deducted"


def resource_extract_billing_rule() -> str:
    return "if actual_cost_cny > 0 then ceil(actual_cost_cny / 0.1) else 0"


def _round_cost(cost: Decimal) -> Decimal:
    return cost.quantize(Decimal("0.000001"))


def _compute_points_from_cost(cost_cny: Decimal) -> int:
    if cost_cny <= 0:
        return 0
    return int((cost_cny / POINTS_UNIT_CNY).to_integral_value(rounding=ROUND_CEILING))


def _calculate_usage_cost_cny(model: str, usage: Dict[str, int]) -> Decimal:
    return _round_cost(calculate_deepseek_v4_flash_usage_cost_cny(usage))


@dataclass
class ResourceExtractionBillingTracker:
    user_id: int | None
    team_id: int | None
    task_id: str | None
    actual_cost_cny: Decimal = field(default_factory=lambda: Decimal("0"))
    charged_points: int = 0
    actual_points: int = 0
    points_status: str = POINTS_STATUS_FREE
    billing_detail: list[Dict[str, Any]] = field(default_factory=list)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "charged_points": int(self.charged_points),
            "actual_points": int(self.actual_points),
            "actual_cost_cny": float(_round_cost(self.actual_cost_cny)),
            "points_status": self.points_status,
            "billing_rule": resource_extract_billing_rule(),
            "billing_detail": list(self.billing_detail),
        }

    def _sync_task_job(self) -> None:
        if not self.task_id:
            return
        update_task_job(
            self.task_id,
            actual_cost_cny=float(_round_cost(self.actual_cost_cny)),
            charged_points=int(self.charged_points),
            actual_points=int(self.actual_points),
            points_status=self.points_status,
            billing_detail=self.billing_detail,
        )

    def record_usage(self, phase: str, model: str, usage: Dict[str, int]) -> None:
        cost_cny = _calculate_usage_cost_cny(model, usage)
        if cost_cny <= 0 and not any(int(usage.get(key) or 0) for key in usage):
            self._sync_task_job()
            return

        self.actual_cost_cny = _round_cost(self.actual_cost_cny + cost_cny)
        target_points = _compute_points_from_cost(self.actual_cost_cny)
        delta = target_points - self.charged_points

        if delta > 0:
            with Session(engine) as session:
                user = session.get(User, self.user_id) if self.user_id is not None else None
                team = session.get(Team, self.team_id) if self.team_id is not None else None
                if not user or not team:
                    raise RuntimeError("resource extract billing context missing")
                deduct_inspiration_points(
                    user=user,
                    team=team,
                    cost=delta,
                    action_type="resource_extract" if self.charged_points == 0 else "resource_extract_delta",
                    description=f"资产提取 {phase}",
                    session=session,
                )
                session.commit()
            self.charged_points = target_points

        self.actual_points = target_points
        self.points_status = POINTS_STATUS_DEDUCTED if self.charged_points > 0 else POINTS_STATUS_FREE
        self.billing_detail.append(
            {
                "phase": phase,
                "model": model,
                "prompt_cache_hit_tokens": int(usage.get("prompt_cache_hit_tokens") or 0),
                "prompt_cache_miss_tokens": int(usage.get("prompt_cache_miss_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "thinking_enabled": bool(usage.get("thinking_enabled")),
                "cost_cny": float(cost_cny),
                "charged_points_after_call": int(self.charged_points),
            }
        )
        self._sync_task_job()


def run_resource_extract_task(task_id: str, payload: Dict[str, Any]) -> None:
    script_id = int(payload["script_id"])
    user_id = int(payload["user_id"]) if payload.get("user_id") is not None else None
    team_id = int(payload["team_id"]) if payload.get("team_id") is not None else None
    script_name = str(payload.get("script_name") or "").strip() or "提取项目资产"

    def _sync_registry(status: str, msg: str, *, progress: int | None = None, result: Dict[str, Any] | None = None, error: Dict[str, Any] | None = None, refresh_hints: Dict[str, bool] | None = None) -> None:
        existing = resource_extract_tasks.get(task_id)
        merged_result = dict(existing.get("result") or {}) if existing else {}
        if isinstance(result, dict):
            merged_result.update(result)
        payload_data = {
            "status": status,
            "msg": msg,
            "script_id": script_id,
            "user_id": user_id,
            "team_id": team_id,
            "assistant_session_id": payload.get("assistant_session_id"),
            "kind": "asset_extract",
            "source": "agent",
            "title": "提取项目资产",
            "summary": script_name,
            "progress": progress,
            "result": merged_result,
            "asset_quality_warnings": merged_result.get("asset_quality_warnings") or [],
            "error": error or {},
            "refresh_hints": refresh_hints or {},
        }
        if existing:
            resource_extract_tasks.update(task_id, **payload_data)
        else:
            resource_extract_tasks.create(task_id, **payload_data)

    if is_task_cancel_requested(task_id):
        update_task_job(task_id, status=TASK_STATUS_CANCELLED, message="资产提取已取消")
        _sync_registry("cancelled", "资产提取已取消")
        return

    job = get_task_job(task_id)
    source_text = str(payload.get("source_text") or "").strip()
    style_prompt = str(payload.get("style_prompt") or "").strip()
    style_label = str(payload.get("style_label") or "").strip()
    billing_tracker = ResourceExtractionBillingTracker(
        user_id=user_id if user_id is not None else (int(job.user_id) if job and job.user_id is not None else None),
        team_id=team_id if team_id is not None else (int(job.team_id) if job and job.team_id is not None else None),
        task_id=task_id,
    )

    def _stage_callback(stage: str, progress: int, message: str, extra: Dict[str, Any] | None = None) -> None:
        update_task_job(
            task_id,
            status="running",
            stage=stage,
            progress=progress,
            message=message,
            result=extra or None,
        )
        _sync_registry("running", message, progress=progress, result=extra)

    def _sync_partial_assets(stage: str, partial_assets: Dict[str, Any]) -> None:
        partial_assets = partial_assets if isinstance(partial_assets, dict) else {}
        _sync_registry(
            "running",
            "资产提取进行中",
            result={
                "partial_assets": {
                    "stage": stage,
                    "characters": list(partial_assets.get("characters") or []),
                    "scenes": list(partial_assets.get("scenes") or []),
                    "props": list(partial_assets.get("props") or []),
                }
            },
        )

    try:
        _sync_registry("running", "资产提取任务开始执行", progress=5)
        _stage_callback("extracting", 10, "AI 正在抽取角色、场景、道具资产...")
        result = extract_script_assets_into_shared_resources(
            script_id,
            source_text,
            settings.DEEPSEEK_API_KEY,
            style_prompt=style_prompt,
            style_label=style_label,
            stage_callback=_stage_callback,
            usage_callback=billing_tracker.record_usage,
            sync_callback=_sync_partial_assets,
        )
        result["billing"] = billing_tracker.snapshot()
        extracted_total = int(result.get("character_count") or 0) + int(result.get("scene_count") or 0) + int(result.get("prop_count") or 0)
        if extracted_total <= 0:
            raise ValueError("未识别到可写入资产库的人物、场景或道具，请调整原文后重试")
        mark_task_job_succeeded(
            task_id,
            result=result,
            message=(
                "资产提取完成：角色 {character_count}，场景 {scene_count}，道具 {prop_count}，新增 {created_count}，更新 {updated_count}"
            ).format(**result),
        )
        update_task_job(
            task_id,
            actual_cost_cny=result["billing"]["actual_cost_cny"],
            charged_points=result["billing"]["charged_points"],
            actual_points=result["billing"]["actual_points"],
            points_status=result["billing"]["points_status"],
            billing_detail=result["billing"]["billing_detail"],
        )
        _sync_registry(
            "completed",
            "资产提取完成，已自动写入资产库",
            progress=100,
            result=result,
            refresh_hints={"resources": True, "assets": True, "open_assets": True},
        )
    except Exception as exc:
        mark_task_job_failed(
            task_id,
            error_code="resource_extract_failed",
            error_message=str(exc),
            message="资产提取失败",
            result={"error": str(exc)},
            retryable=False,
        )
        _sync_registry(
            "failed",
            "资产提取失败",
            error={"message": str(exc)},
            refresh_hints={"resources": True},
        )


def run_resource_reference_image_task(task_id: str, payload: Dict[str, Any]) -> None:
    if is_task_cancel_requested(task_id):
        update_task_job(task_id, status=TASK_STATUS_CANCELLED, message="资源参考图生成已取消")
        return

    try:
        update_task_job(
            task_id,
            status="running",
            stage="submitting",
            progress=10,
            message="资源参考图正在生成...",
        )
        result = run_shared_resource_generation(
            resource_id=int(payload["resource_id"]),
            prompt=str(payload["prompt"] or ""),
            channel=str(payload.get("model_code") or payload.get("channel") or "nano-banana-pro"),
            resolution=str(payload.get("resolution") or "2k"),
            quality=str(payload.get("quality") or "medium"),
            aspect_ratio=str(payload.get("aspect_ratio") or "1:1"),
            reference_images=list(payload.get("reference_images") or []),
            version_tag=payload.get("version_tag"),
            start_seq=payload.get("start_seq"),
            end_seq=payload.get("end_seq"),
            is_default=bool(payload.get("is_default", True)),
        )
        record_id = payload.get("record_id")
        if record_id:
            _complete_record_success(int(record_id), preview_url=str(result.get("file_url") or ""), thumbnail_url="")
        mark_task_job_succeeded(
            task_id,
            result=result,
            message="资源参考图生成完成",
        )
    except Exception as exc:
        record_id = payload.get("record_id")
        if record_id:
            _mark_failed(
                int(record_id),
                error_code="resource_generate_failed",
                message="资源参考图生成失败，请稍后重试",
                internal_message=str(exc),
            )
        mark_task_job_failed(
            task_id,
            error_code="resource_generate_failed",
            error_message=str(exc),
            message="资源参考图生成失败",
            result={"error": str(exc)},
            retryable=False,
        )
