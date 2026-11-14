"""分析导出中心业务规则：状态流转、字段校验、导出文件与筛选口径都收在这里。

导出任务在登记时就把「字段选择、筛选条件、导出上限」和任务一起落库，
所以列表页、导出入口与数据目录检索读到的是同一份字段清单。

分析导出文件按任务编号唯一：重复开始同一导出只保留一份文件（配置一致时沿用
已生成文件，配置变化时覆盖同一份）；生成失败时文件清单、文件大小与任务状态
一起回退，不会留下半份结果。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from app.store import store

MODULE = "export"
CATALOG_MODULE = "catalog"
CATALOG_NAME_FIELD = "数据集名称"
CATALOG_FIELDS_FIELD = "字段清单"

REQUIRED_FIELDS = ["任务编号", "数据源名称", "导出格式"]
STATUS_ORDER = ["草稿", "导出中", "已完成", "已过期"]
ACTION_RULES = {
    "开始导出": ("草稿", "导出中"),
    "标记完成": ("导出中", "已完成"),
    "清理文件": ("已完成", "已过期"),
}
NEGATIVE_ACTIONS: list[str] = []

# 与列表页 / 导出入口共用的字段口径：登记时这些字段要和任务一起落库。
PERSISTED_FIELDS = ["字段选择", "筛选条件", "导出上限"]
FORMAT_SUFFIX = {"csv": "csv", "parquet": "parquet", "xlsx": "xlsx", "json": "json"}
DEFAULT_FORMAT = "CSV"
# 导出文件默认行数上限；任务没有填写导出上限时按这个口径估算文件大小。
DEFAULT_ROW_LIMIT = 100_000
# 历史任务缺少字段选择时的补齐口径：优先取数据目录里同名数据集的字段清单。
DEFAULT_FIELDS = "dataset_id,metric_value,stat_date"

_FIELD_SPLIT = re.compile(r"[,，、\s]+")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _split_fields(value: Any) -> list[str]:
    """字段选择按中英文分隔符拆开，保持原有顺序。"""
    return [item for item in _FIELD_SPLIT.split(_text(value)) if item]


def _parse_limit(value: Any) -> tuple[int, str]:
    """导出上限必须是正整数；留空按默认上限，非法取值给出可读原因。"""
    raw = _text(value)
    if not raw:
        return DEFAULT_ROW_LIMIT, ""
    if not raw.isdigit():
        return 0, f"导出上限「{raw}」不是有效数字"
    limit = int(raw)
    if limit <= 0:
        return 0, f"导出上限「{raw}」必须大于 0"
    return limit, ""


def _fingerprint(source: str, fmt: str, fields: list[str], conditions: str, limit: int) -> str:
    """同一任务同一配置算出同一指纹，重复开始时据此沿用已生成文件。"""
    raw = "|".join([source, fmt.lower(), ",".join(fields), _text(conditions), str(limit)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _file_size(fmt: str, fields: list[str], limit: int) -> int:
    """按导出格式、字段数与行数上限估算文件大小；结果确定、可逐字节核对。"""
    suffix = FORMAT_SUFFIX.get(fmt.lower(), "csv")
    per_row = {"csv": 12, "parquet": 8, "xlsx": 16, "json": 20}.get(suffix, 12)
    width = max(len(fields), 1)
    return max(1, limit * width * per_row // 100 + width * 4)


class ExportService:
    def __init__(self) -> None:
        self._backfill_initial_rows()

    # ---- 列表与详情 ----

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        task_no: str | None = None,
        source: str | None = None,
        file_format: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        self._backfill_missing_fields(rows)
        if keyword:
            keyword = keyword.strip()
            rows = [
                row
                for row in rows
                if keyword in _text(row.get("任务编号")) or keyword in _text(row.get("数据源名称"))
            ]
        if task_no:
            needle = _text(task_no)
            rows = [row for row in rows if needle in _text(row.get("任务编号"))]
        if source:
            needle = _text(source)
            rows = [row for row in rows if needle in _text(row.get("数据源名称"))]
        if file_format:
            needle = _text(file_format)
            rows = [row for row in rows if needle.lower() in _text(row.get("导出格式")).lower()]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int | str) -> dict[str, Any] | None:
        entry = self._resolve(entry_id)
        if entry is None:
            return None
        self._backfill_missing_fields([entry])
        return entry

    def export_files(self, task_no: str | None = None) -> list[dict[str, Any]]:
        """分析导出文件清单；同一任务编号最多一份。"""
        return store.export_files(task_no)

    # ---- 登记 ----

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """登记导出任务：字段选择、筛选条件与导出上限和任务一起落库。"""
        missing = [field for field in REQUIRED_FIELDS if not _text(values.get(field))]
        if missing:
            return None, missing
        with store.lock:
            rows = store.rows(MODULE)
            entry: dict[str, Any] = {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1
            }
            entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
            # 原样保存字段选择与筛选条件，避免筛选结果和列表错位。
            entry["字段选择"] = _text(values.get("字段选择"))
            entry["筛选条件"] = _text(values.get("筛选条件")) or "无"
            entry["导出上限"] = _text(values.get("导出上限")) or str(DEFAULT_ROW_LIMIT)
            entry["文件大小"] = "0"
            entry["status"] = STATUS_ORDER[0]
            entry["任务状态"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            rows.append(entry)
            # 登记时就补齐缺失的字段选择，避免列表页与导出入口各读一份口径。
            self._backfill_missing_fields([entry])
        return entry, []

    # ---- 动作 ----

    def run_action(
        self, entry_id: int | str, action: str
    ) -> tuple[dict[str, Any] | None, str]:
        entry = self._resolve(entry_id)
        if entry is None:
            return None, f"导出任务 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于分析导出中心可执行范围"

        code = _text(entry.get("任务编号")) or str(entry_id)
        current = _text(entry.get("status")) or STATUS_ORDER[0]
        _required, target = ACTION_RULES[action]

        # 重复点击同一动作时沿用当前已落地的结果，不重复生成文件。
        if current == target:
            if action == "开始导出" and not store.export_files(code):
                # 任务停在「导出中」但还没有文件（例如上次打包中断），继续生成这一份。
                return self._start_export(entry, code)
            if action == "开始导出":
                self._ensure_single_file(entry)
            return entry, f"导出任务 {code} 已处于「{current}」，沿用当前结果"

        if current == STATUS_ORDER[-1]:
            return None, f"导出任务 {code} 已过期，不能恢复"
        if current != _required:
            return None, (
                f"导出任务 {code} 当前为「{current}」，不能执行「{action}」；"
                "状态需按 草稿→导出中→已完成→已过期 连续流转"
            )

        if action == "开始导出":
            return self._start_export(entry, code)
        if action == "清理文件":
            return self._cleanup(entry, code)

        with store.lock:
            entry["status"] = target
            entry["任务状态"] = target
            entry["pending"] = target != STATUS_ORDER[-1]
            entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"导出任务已{action}"

    # ---- 开始导出：一任务一文件，失败整体回退 ----

    def _start_export(
        self, entry: dict[str, Any], code: str
    ) -> tuple[dict[str, Any] | None, str]:
        self._backfill_missing_fields([entry])
        fields = _split_fields(entry.get("字段选择"))
        if not fields:
            self._mark_abnormal(entry)
            return None, f"导出任务 {code} 没有可用的字段选择，未开始导出"

        limit, error = _parse_limit(entry.get("导出上限"))
        if error:
            self._mark_abnormal(entry)
            return None, f"导出任务 {code} 未开始导出：{error}"

        source = _text(entry.get("数据源名称"))
        fmt = _text(entry.get("导出格式")) or DEFAULT_FORMAT
        conditions = _text(entry.get("筛选条件"))
        fingerprint = _fingerprint(source, fmt, fields, conditions, limit)

        existing = store.export_files(code)
        if existing and _text(existing[0].get("文件指纹")) == fingerprint:
            # 配置未变化：沿用同一份分析导出文件，不新增也不重写。
            with store.lock:
                entry["status"] = "导出中"
                entry["任务状态"] = "导出中"
                entry["pending"] = True
                entry["abnormal"] = False
                entry["文件指纹"] = fingerprint
                entry["文件大小"] = str(existing[0].get("文件大小"))
            return entry, (
                f"导出任务 {code} 已生成相同配置的分析导出文件，直接沿用"
                f"（文件大小 {existing[0].get('文件大小')}）"
            )

        previous = {
            "status": entry.get("status"),
            "任务状态": entry.get("任务状态"),
            "pending": entry.get("pending"),
            "abnormal": entry.get("abnormal"),
            "文件大小": entry.get("文件大小"),
        }
        snapshot = store.snapshot_export_files()
        try:
            size = _file_size(fmt, fields, limit)
            if size <= 0:
                raise ValueError("导出内容为空，无法生成文件")
            file = {
                "任务编号": code,
                "数据源名称": source,
                "导出格式": fmt,
                # 文件与任务保存同一份字段选择原文，列表页与导出入口可直接逐字核对。
                "字段选择": _text(entry.get("字段选择")),
                "筛选条件": conditions,
                "导出上限": str(limit),
                "文件大小": size,
                "文件指纹": fingerprint,
            }
            with store.lock:
                # 按任务编号 upsert：重复开始同一导出只保留一个分析导出文件。
                store.replace_export_file(file)
                entry["status"] = "导出中"
                entry["任务状态"] = "导出中"
                entry["pending"] = True
                entry["abnormal"] = False
                entry["文件大小"] = str(size)
                entry["文件指纹"] = fingerprint
        except Exception:
            # 文件与任务同进同退：文件清单撤回到本次之前的版本，
            # 任务状态与文件大小也退回本次之前的取值。
            with store.lock:
                store.restore_export_files(snapshot)
                entry.update(previous)
                entry.pop("文件指纹", None)
            entry["abnormal"] = True
            return None, f"导出任务 {code} 生成分析导出文件失败，文件大小与任务状态已回退"

        return entry, f"导出任务已开始导出，文件大小 {size} 字节（同一导出只保留一份文件）"

    def _cleanup(self, entry: dict[str, Any], code: str) -> tuple[dict[str, Any] | None, str]:
        with store.lock:
            store.remove_export_files(code)
            entry["status"] = "已过期"
            entry["任务状态"] = "已过期"
            entry["pending"] = False
            entry["abnormal"] = True
            entry["文件大小"] = "0"
            entry.pop("文件指纹", None)
        return entry, f"导出任务 {code} 已清理文件，分析导出文件已从清单移除"

    def _ensure_single_file(self, entry: dict[str, Any]) -> None:
        """重复开始导出时兜底：同一任务若残留多份文件，只保留最新一份。"""
        code = _text(entry.get("任务编号"))
        files = store.export_files(code)
        if len(files) > 1:
            store.replace_export_file(files[-1])

    @staticmethod
    def _mark_abnormal(entry: dict[str, Any]) -> None:
        entry["abnormal"] = True

    # ---- 历史任务补齐 ----

    def _backfill_initial_rows(self) -> None:
        self._backfill_missing_fields(store.rows(MODULE))

    def _backfill_missing_fields(self, rows: list[dict[str, Any]]) -> None:
        """历史导出任务缺少字段选择时按数据目录补齐，补齐结果写回任务。

        优先取数据目录里同名「数据集名称」的字段清单；目录没有登记时退回
        默认字段清单。列表页与导出入口都走同一份补齐逻辑，因此不会各读一份值。
        """
        for row in rows:
            changed = False
            if not _text(row.get("字段选择")):
                row["字段选择"] = self._catalog_fields(row) or DEFAULT_FIELDS
                changed = True
            if not _text(row.get("筛选条件")):
                row["筛选条件"] = "无"
                changed = True
            if not _text(row.get("导出上限")):
                row["导出上限"] = str(DEFAULT_ROW_LIMIT)
                changed = True
            if not _text(row.get("文件大小")):
                row["文件大小"] = "0"
            if changed:
                row["字段选择补齐"] = True

    @staticmethod
    def _catalog_fields(row: dict[str, Any]) -> str:
        entry = store.find_by_code(
            CATALOG_MODULE, CATALOG_NAME_FIELD, _text(row.get("数据源名称"))
        )
        if entry is None:
            return ""
        return _text(entry.get(CATALOG_FIELDS_FIELD))

    # ---- 定位任务：兼容任务编号与内部 id ----

    @staticmethod
    def _resolve(ref: int | str) -> dict[str, Any] | None:
        text = _text(ref)
        if text.isdigit():
            found = store.find(MODULE, int(text))
            if found is not None:
                return found
        return store.find_by_code(MODULE, "任务编号", text)
