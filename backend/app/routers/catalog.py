"""数据目录检索接口：维护目录条目，覆盖发布条目、下线条目、归档条目等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.catalog import CatalogService

router = APIRouter(prefix="/api/catalog", tags=["数据目录检索"])

service = CatalogService()

LIST_FIELDS = ["条目编号", "数据集名称", "业务域", "字段清单", "更新频率", "数据等级", "负责人", "条目状态"]
STATUSES = ["草稿", "已发布", "已下线", "已归档"]

@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按条目编号或数据集名称检索"),
    status: str | None = Query(default=None, description="草稿、已发布、已下线、已归档"),
    entry_no: str | None = Query(default=None, alias="条目编号", description="按条目编号检索"),
    dataset: str | None = Query(default=None, alias="数据集名称", description="按数据集名称检索"),
    domain: str | None = Query(default=None, alias="业务域", description="按业务域检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按条目编号、数据集名称、业务域与状态过滤数据目录检索列表。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword,
        status=status,
        entry_no=entry_no,
        dataset=dataset,
        domain=domain,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)

@router.get("/export")
def export_entries(
    keyword: str | None = Query(default=None, description="按条目编号或数据集名称检索"),
    status: str | None = Query(default=None, description="草稿、已发布、已下线、已归档"),
    entry_no: str | None = Query(default=None, alias="条目编号", description="按条目编号检索"),
    dataset: str | None = Query(default=None, alias="数据集名称", description="按数据集名称检索"),
    domain: str | None = Query(default=None, alias="业务域", description="按业务域检索"),
) -> dict[str, Any]:
    """导出数据目录检索清单：按当前过滤条件返回整套条目，字段清单与列表页一致。"""
    items, total = service.list_entries(
        keyword=keyword,
        status=status,
        entry_no=entry_no,
        dataset=dataset,
        domain=domain,
        page=1,
        size=100000,
    )
    return {"module": "catalog", "total": total, "items": items}

@router.get("/fields/{dataset_name}", response_model=dict)
def dataset_fields(dataset_name: str) -> dict[str, Any]:
    """按数据集名称读取字段清单，供分析导出中心核对导出文件引用的字段。"""
    item = service.find_by_dataset(dataset_name)
    if item is None:
        raise HTTPException(status_code=404, detail=f"数据目录中找不到数据集「{dataset_name}」")
    return item

@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: str) -> dict:
    """读取单条目录条目明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"目录条目 {entry_id} 不存在或已归档")
    return entry

@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条目录条目，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.resolved_values())
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="目录条目已登记", entry=entry)

@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: str, payload: EntryPayload) -> ActionResult:
    """对单条目录条目执行发布条目、下线条目、归档条目；不允许的动作会被拦下并说明原因。"""
    action = str(payload.resolved_values().get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)

