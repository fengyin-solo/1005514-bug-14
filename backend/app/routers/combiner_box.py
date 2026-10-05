"""汇流箱检测接口：维护汇流箱，覆盖恢复正常、标记异常、停用设备等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.combiner_box import CombinerBoxService

router = APIRouter(prefix="/api/combiner_box", tags=["汇流箱检测"])

service = CombinerBoxService()

LIST_FIELDS = ["汇流箱编号", "所属阵列", "输入路数", "熔断器状态", "防雷模块状态", "通讯状态", "箱体温度", "运行状态"]
STATUSES = ["运行正常", "熔断器异常", "通讯中断", "已停用"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按汇流箱编号检索"),
    status: str | None = Query(default=None, description="运行正常、熔断器异常、通讯中断、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按汇流箱编号与状态过滤汇流箱检测列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条汇流箱明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"汇流箱 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条汇流箱，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="汇流箱已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条汇流箱执行恢复正常、标记异常、停用设备；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出汇流箱检测清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "combiner_box", "total": total, "items": items}
