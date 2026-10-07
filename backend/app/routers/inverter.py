"""逆变器监视接口：维护逆变器，覆盖恢复运行、降容保护、升级高温报警、安排检修等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.inverter import InverterService

router = APIRouter(prefix="/api/inverter", tags=["逆变器监视"])

service = InverterService()

LIST_FIELDS = ["逆变器编号", "品牌型号", "额定功率", "输入电压范围", "所属阵列", "运行温度", "日均发电量", "运行状态"]
STATUSES = ["正常运行", "降容运行", "高温报警", "待检修"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按逆变器编号检索"),
    status: str | None = Query(default=None, description="正常运行、降容运行、高温报警、待检修"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按逆变器编号与状态过滤逆变器监视列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries(
    keyword: str | None = Query(default=None, description="按逆变器编号检索"),
    status: str | None = Query(default=None, description="正常运行、降容运行、高温报警、待检修"),
) -> dict[str, Any]:
    """导出逆变器监视清单：与列表走同一份查询，已停用机组不计入，条数与列表一致。"""
    items, total = service.list_entries(keyword=keyword, status=status, page=1, size=10000)
    return {"module": "inverter", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条逆变器明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"逆变器 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条逆变器，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="逆变器已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """回写额定功率等业务字段；保存后列表、单条与导出读到同一份数据。"""
    entry, message = service.update_entry(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条逆变器执行恢复运行、降容保护、升级高温报警、安排检修；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
