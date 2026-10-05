"""光伏阵列接口：维护光伏阵列，覆盖恢复全功率、降功率运行、申请停机等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.pv_array import PvArrayService

router = APIRouter(prefix="/api/pv_array", tags=["光伏阵列"])

service = PvArrayService()

LIST_FIELDS = ["阵列编号", "所属片区", "组件型号", "单块功率", "串联片数", "总装机容量", "投运日期", "阵列状态"]
STATUSES = ["运行中", "限功率", "计划停机", "故障停机"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按阵列编号检索"),
    status: str | None = Query(default=None, description="运行中、限功率、计划停机、故障停机"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按阵列编号与状态过滤光伏阵列列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条光伏阵列明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"光伏阵列 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条光伏阵列，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="光伏阵列已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条光伏阵列执行恢复全功率、降功率运行、申请停机；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出光伏阵列清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "pv_array", "total": total, "items": items}
