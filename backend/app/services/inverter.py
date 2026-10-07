"""逆变器监视业务规则：状态流转、字段校验与筛选口径都收在这里。

约定：
- status 是唯一状态源，运行状态字段只在回写时同步，读取时兜底校准，兼容旧记录；
- 状态沿 正常运行 → 降容运行 → 高温报警 依次流转，只允许前进，不允许回到上一档；
- 降容保护对同一台设备只生效一次，重复提交不再改变状态、不重复生成检修待办；
- 额定功率等档案字段通过 update_entry 进库，列表、单条、导出走同一份数据。
"""
from __future__ import annotations

from typing import Any

from app.services.maintenance import MaintenanceService
from app.store import store

MODULE = "inverter"
REQUIRED_FIELDS = ["逆变器编号", "品牌型号", "额定功率"]
EDITABLE_FIELDS = ["逆变器编号", "品牌型号", "额定功率", "输入电压范围", "所属阵列", "运行温度", "日均发电量"]
STATUS_ORDER = ["正常运行", "降容运行", "高温报警", "待检修"]
ACTION_RULES = {"降容保护": "降容运行", "高温报警": "高温报警", "安排检修": "待检修"}
# 依次流转的允许路径：只能前进到下一档或转待检修，不允许回到上一档。
TRANSITIONS = {
    "正常运行": ["降容运行", "待检修"],
    "降容运行": ["高温报警", "待检修"],
    "高温报警": ["待检修"],
    "待检修": [],
}
NEGATIVE_ACTIONS = ["降容保护", "高温报警"]
DERATE_ACTION = "降容保护"
DERATE_CATEGORY = "降容处置"

maintenance_service = MaintenanceService()


class InverterService:
    def _normalize(self, row: dict[str, Any]) -> dict[str, Any]:
        """校准单条记录：旧记录可能缺键或运行状态与 status 不一致，读取时兜底。"""
        status = str(row.get("status") or STATUS_ORDER[0])
        if status not in STATUS_ORDER:
            status = STATUS_ORDER[0]
        row["status"] = status
        row["运行状态"] = status
        row.setdefault("pending", status != STATUS_ORDER[-1])
        row.setdefault("abnormal", False)
        return row

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [self._normalize(row) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("逆变器编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self._normalize(entry)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS:
            entry[field] = self._clean(values.get(field))
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._normalize(entry), []

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """档案字段回写：额定功率等修改在这里进库，状态只能走动作接口流转。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"逆变器 {entry_id} 不存在或已归档"
        provided = [field for field in EDITABLE_FIELDS if field in values]
        if not provided:
            return None, "没有可更新的字段"
        changed: list[str] = []
        for field in provided:
            value = self._clean(values.get(field))
            if field in REQUIRED_FIELDS and not value:
                return None, f"{field}不能为空"
            if entry.get(field) != value:
                entry[field] = value
                changed.append(field)
        if not changed:
            return self._normalize(entry), "提交的值与现有档案一致，无变化"
        return self._normalize(entry), f"逆变器档案已更新：{'、'.join(changed)}"

    def run_action(
        self,
        entry_id: int,
        action: str,
        remark: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"逆变器 {entry_id} 不存在或已归档"
        self._normalize(entry)
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于逆变器监视可执行范围"
        current = str(entry["status"])
        target = ACTION_RULES[action]
        if target == current:
            # 同一台设备重复提交只生效一次：状态不变，也不重复生成检修待办。
            if action == DERATE_ACTION:
                return entry, f"逆变器 {entry.get('逆变器编号', entry_id)} 已处于降容运行，重复提交不再生效"
            return entry, f"逆变器已处于{current}，无需重复{action}"
        if target not in TRANSITIONS.get(current, []):
            if STATUS_ORDER.index(target) < STATUS_ORDER.index(current):
                return None, f"状态不允许回到上一档（当前：{current}，目标：{target}）"
            return None, f"状态需依次流转（{' → '.join(STATUS_ORDER[:3])}），当前「{current}」不能直接到「{target}」"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        self._normalize(entry)
        if action == DERATE_ACTION:
            conclusion = self._record_derate_todo(entry, remark)
            return entry, f"逆变器已降容保护，处置结论已写入检修计划待办：{conclusion}"
        return entry, f"逆变器已{action}"

    def _record_derate_todo(self, entry: dict[str, Any], remark: str | None) -> str:
        """把降容处置结论落到检修计划的待办事项；同一台设备只落一条，重复提交不重复建。"""
        code = str(entry.get("逆变器编号") or entry.get("id"))
        conclusion = str(remark or "").strip() or f"逆变器{code}降容运行，需安排检修跟进"
        for row in store.rows("maintenance"):
            if row.get("检修设备") == code and row.get("检修类别") == DERATE_CATEGORY:
                return str(row.get("待办事项") or conclusion)
        todo, _ = maintenance_service.create_entry({
            "计划编号": self._next_maintenance_code(),
            "检修设备": code,
            "检修类别": DERATE_CATEGORY,
        })
        if todo is not None:
            todo["待办事项"] = conclusion
            todo["关联逆变器"] = code
            todo["计划状态"] = str(todo.get("status") or "待审批")
        return conclusion

    @staticmethod
    def _next_maintenance_code() -> str:
        rows = store.rows("maintenance")
        next_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        return f"MAIN-{next_id:04d}"

    @staticmethod
    def _clean(value: Any) -> str:
        return str(value or "").strip()
