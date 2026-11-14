"""数据目录检索业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

import re
from typing import Any

from app.store import store

MODULE = "catalog"
CODE_FIELDS = ["条目编号"]
REQUIRED_FIELDS = ["条目编号", "数据集名称", "业务域"]
STATUS_ORDER = ["草稿", "已发布", "已下线", "已归档"]
ACTION_RULES = {"发布条目": "草稿", "下线条目": "已发布", "归档条目": "已下线"}
NEGATIVE_ACTIONS = ["下线条目"]


def _entry_fields(entry: dict[str, Any]) -> str:
    """条目当前生效的字段清单；缺失时返回空串而不是占位文案。"""
    return str(entry.get("字段清单") or "").strip()


def _split_fields(value: Any) -> list[str]:
    return [item for item in re.split(r"[,，、\s]+", _entry_fields({"字段清单": value})) if item]


def _normalize(entry: dict[str, Any]) -> dict[str, Any]:
    """详情/列表统一出口：任务状态与字段清单只保留一份，避免重复展示。"""
    row = dict(entry)
    row["条目状态"] = row.get("status")
    row["字段清单"] = _entry_fields(entry)
    return row


class CatalogService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        entry_no: str | None = None,
        dataset: str | None = None,
        domain: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("条目编号", ""))
                or keyword in str(row.get("数据集名称", ""))
            ]
        if entry_no:
            rows = [row for row in rows if str(entry_no).strip() in str(row.get("条目编号", ""))]
        if dataset:
            rows = [row for row in rows if str(dataset).strip() in str(row.get("数据集名称", ""))]
        if domain:
            rows = [row for row in rows if str(domain).strip() in str(row.get("业务域", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int | str) -> dict[str, Any] | None:
        """兼容内部自增 id 与业务编号（如 CATA-0001）两种定位方式。"""
        entry = self._resolve(entry_id)
        if entry is None:
            return None
        # 详情与列表读同一份字段清单，避免字段选择/筛选条件各读一份值。
        return {**_normalize(entry), "字段清单": _entry_fields(entry)}

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        if str(values.get("字段清单") or "").strip():
            entry["字段清单"] = values.get("字段清单")
        entry["status"] = STATUS_ORDER[0]
        entry["条目状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int | str, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = self._resolve(entry_id)
        if entry is None:
            return None, f"目录条目 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据目录检索可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["条目状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return _normalize(entry), f"目录条目已{action}"

    def export_view(self) -> list[dict[str, Any]]:
        """目录清单导出：与列表页共用同一份字段清单与状态口径。"""
        return [_normalize(row) for row in store.rows(MODULE)]

    def find_by_dataset(self, dataset: str) -> dict[str, Any] | None:
        """按数据集名称读取目录条目，导出侧据此核对字段选择与筛选条件。"""
        row = store.find_by_code(MODULE, "数据集名称", str(dataset or "").strip())
        if row is None:
            return None
        return {**_normalize(row), "字段": _split_fields(_entry_fields(row))}

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
