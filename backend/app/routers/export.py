"""分析导出中心接口：维护导出任务，覆盖开始导出、标记完成、清理文件等动作。

导出入口 ``/export`` 是固定路径，必须声明在 ``/{entry_id}`` 之前，否则会被
单条任务路由截获并当成 entry_id 解析，返回参数错误。导出入口按页面此刻的
过滤条件返回整套任务，不退化成单条详情。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.export import ExportService

router = APIRouter(prefix="/api/export", tags=["分析导出中心"])

service = ExportService()

LIST_FIELDS = ["任务编号", "数据源名称", "导出格式", "字段选择", "筛选条件", "导出上限", "文件大小", "任务状态"]
STATUSES = ["草稿", "导出中", "已完成", "已过期"]


def _list(
    *,
    keyword: str | None,
    status: str | None,
    task_no: str | None,
    source: str | None,
    file_format: str | None,
    page: int,
    size: int,
) -> tuple[list[dict[str, Any]], int]:
    return service.list_entries(
        keyword=keyword,
        status=status,
        task_no=task_no,
        source=source,
        file_format=file_format,
        page=page,
        size=size,
    )

@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按任务编号或数据源名称检索"),
    status: str | None = Query(default=None, description="草稿、导出中、已完成、已过期"),
    task_no: str | None = Query(default=None, alias="任务编号", description="按任务编号检索"),
    source: str | None = Query(default=None, alias="数据源名称", description="按数据源名称检索"),
    file_format: str | None = Query(default=None, alias="导出格式", description="按导出格式检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按任务编号、数据源名称、导出格式与状态过滤分析导出中心列表。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = _list(
        keyword=keyword,
        status=status,
        task_no=task_no,
        source=source,
        file_format=file_format,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)

@router.get("/export")
def export_entries(
    keyword: str | None = Query(default=None, description="按任务编号或数据源名称检索"),
    status: str | None = Query(default=None, description="草稿、导出中、已完成、已过期"),
    task_no: str | None = Query(default=None, alias="任务编号", description="按任务编号检索"),
    source: str | None = Query(default=None, alias="数据源名称", description="按数据源名称检索"),
    file_format: str | None = Query(default=None, alias="导出格式", description="按导出格式检索"),
) -> dict[str, Any]:
    """导出分析导出中心清单：按当前过滤条件返回整套任务，不返回单条详情。"""
    items, total = _list(
        keyword=keyword,
        status=status,
        task_no=task_no,
        source=source,
        file_format=file_format,
        page=1,
        size=100000,
    )
    return {"module": "export", "total": total, "items": items}

@router.get("/files", response_model=dict)
def list_files(task_no: str | None = Query(default=None, description="按任务编号过滤")) -> dict[str, Any]:
    """分析导出文件清单：同一任务编号最多一份，重复开始导出不会产生第二份。"""
    files = service.export_files(task_no)
    return {"items": files, "total": len(files)}

@router.get("/files/{task_no}", response_model=dict)
def get_file(task_no: str) -> dict[str, Any]:
    """读取某个导出任务的分析导出文件；不存在时给出可读说明。"""
    files = service.export_files(task_no)
    if not files:
        raise HTTPException(status_code=404, detail=f"导出任务 {task_no} 尚未生成分析导出文件")
    return files[0]


# 注意：``/{entry_id}`` 必须排在 ``/export`` 与 ``/files`` 之后。

@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: str) -> dict:
    """读取单条导出任务明细；既接受内部 id，也接受 EXPO-0001 这样的任务编号。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"导出任务 {entry_id} 不存在或已归档")
    entry = dict(entry)
    entry["分析导出文件"] = service.export_files(str(entry.get("任务编号") or ""))
    return entry

@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条导出任务；字段选择与筛选条件随任务一起落库，不静默丢弃。"""
    entry, missing = service.create_entry(payload.resolved_values())
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="导出任务已登记", entry=entry)

@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: str, payload: EntryPayload) -> ActionResult:
    """开始导出、标记完成、清理文件；导出失败时文件与任务状态一起回退。"""
    action = str(payload.resolved_values().get("action") or "").strip()
    if not action:
        return ActionResult(ok=False, message="缺少动作名称，请提交 action 字段")
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
