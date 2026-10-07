"""逆变器监视业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.services.maintenance import MaintenanceService
from app.store import store

MODULE = "inverter"
MAINTENANCE_MODULE = "maintenance"
REQUIRED_FIELDS = ["逆变器编号", "品牌型号", "额定功率"]
# 允许通过更新接口回写的业务字段；运行状态只能由状态机驱动，不在其列。
EDITABLE_FIELDS = ["逆变器编号", "品牌型号", "额定功率", "输入电压范围", "所属阵列", "运行温度", "日均发电量"]
STATUS_ORDER = ["正常运行", "降容运行", "高温报警", "待检修"]
STATUS_FIELD = "运行状态"
# 待检修是终态：机组退出运行，默认不再计入在运清单与导出。
TERMINAL_STATUS = STATUS_ORDER[-1]
ACTION_RULES = {"恢复运行": "正常运行", "降容保护": "降容运行", "升级高温报警": "高温报警", "安排检修": "待检修"}
NEGATIVE_ACTIONS = ["降容保护", "升级高温报警"]
DERATE_ACTION = "降容保护"
DERATE_CATEGORY = "降容处置"


class InverterService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if status:
            rows = [row for row in rows if row.get("status") == status]
        else:
            # 已停用（待检修）的机组不属于在运清单；显式按状态查询时仍可取到。
            rows = [row for row in rows if row.get("status") != TERMINAL_STATUS]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("逆变器编号", ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._present(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        return self._present(row)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry[STATUS_FIELD] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._present(entry), []

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """回写额定功率等业务字段；状态类字段只能走动作流转，这里不收。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"逆变器 {entry_id} 不存在或已归档"
        changed: dict[str, Any] = {}
        for field in EDITABLE_FIELDS:
            if field not in values:
                continue
            value = values[field]
            if field in REQUIRED_FIELDS and not str(value or "").strip():
                return None, f"{field} 不能为空"
            changed[field] = value
        if not changed:
            return None, f"没有可更新的字段；仅支持修改：{'、'.join(EDITABLE_FIELDS)}"
        entry.update(changed)
        return self._present(entry), f"逆变器资料已进库：{'、'.join(changed)}"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"逆变器 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于逆变器监视可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        current = entry.get("status")
        current_index = STATUS_ORDER.index(current) if current in STATUS_ORDER else 0
        target_index = STATUS_ORDER.index(target)
        if current == target:
            # 重复提交同一档（如重复降容）只生效一次，不产生新的副作用。
            return self._present(entry), f"逆变器已处于{target}，本次不重复生效"
        if target_index < current_index:
            return None, f"逆变器当前为{current}，不允许回到上一档{target}"
        if target != TERMINAL_STATUS and target_index > current_index + 1:
            return None, f"状态需依次流转，不能从{current}直接变为{target}"
        entry["status"] = target
        entry[STATUS_FIELD] = target
        entry["pending"] = target != TERMINAL_STATUS
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if action == DERATE_ACTION:
            self._record_derate_todo(entry)
        return self._present(entry), f"逆变器已{action}"

    def _record_derate_todo(self, entry: dict[str, Any]) -> None:
        """降容处置结论落到检修计划待办；同一台机组只登记一条未闭环的待办。"""
        code = str(entry.get("逆变器编号") or "").strip() or f"ID-{entry.get('id')}"
        for plan in store.rows(MAINTENANCE_MODULE):
            if (
                str(plan.get("检修设备")) == code
                and plan.get("检修类别") == DERATE_CATEGORY
                and plan.get("pending")
            ):
                return
        plans = store.rows(MAINTENANCE_MODULE)
        next_id = max((int(plan.get("id", 0)) for plan in plans), default=0) + 1
        plan, _ = MaintenanceService().create_entry({
            "计划编号": f"MAIN-{next_id:04d}",
            "检修设备": code,
            "检修类别": DERATE_CATEGORY,
        })
        if plan is None:
            return
        plan["计划状态"] = plan.get("status", "待审批")
        plan["处置结论"] = f"逆变器{code}已执行降容保护：限功率运行，待检修排查高温诱因并复测额定功率"

    def _present(self, row: dict[str, Any]) -> dict[str, Any]:
        """输出前兜底：兼容旧记录，运行状态一律以状态机字段为准。"""
        entry = dict(row)
        status = entry.get("status")
        if status not in STATUS_ORDER:
            status = STATUS_ORDER[0]
            entry["status"] = status
        entry[STATUS_FIELD] = status
        return entry
