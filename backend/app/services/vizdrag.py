"""拖拽可视化业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "vizdrag"
CODE_FIELDS = ["方案编号"]
REQUIRED_FIELDS = ["方案编号", "方案名称", "数据源绑定"]
STATUS_ORDER = ["草稿", "已发布", "已嵌入", "已归档"]
ACTION_RULES = {"发布方案": "草稿", "嵌入看板": "已发布", "归档方案": "已嵌入"}
NEGATIVE_ACTIONS = []


class VizdragService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("方案编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int | str) -> dict[str, Any] | None:
        """兼容内部自增 id 与业务编号（如 MART-0001）两种定位方式。"""
        return self._resolve(entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int | str, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = self._resolve(entry_id)
        if entry is None:
            return None, f"可视化方案 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于拖拽可视化可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"可视化方案已{action}"

    @staticmethod
    def _resolve(ref: int | str) -> dict[str, Any] | None:
        """按内部 id 定位，失败时按业务编号再找一次。"""
        text = str(ref or "").strip()
        if text.isdigit():
            found = store.find(MODULE, int(text))
            if found is not None:
                return found
        for field in CODE_FIELDS:
            found = store.find_by_code(MODULE, field, text)
            if found is not None:
                return found
        return None
