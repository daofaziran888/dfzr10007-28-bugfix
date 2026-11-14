"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。

分析导出文件单独存放（``_export_files``）：一个导出任务同时只允许存在一份
分析导出文件，重复开始导出按任务编号覆盖而不是追加；导出失败时整体回退，
不会在文件清单里留下半份结果。导出文件不参与运营概览的业务模块统计。
"""
from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any

from app.seed import SEED_EXPORT_FILES, SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: deepcopy(rows) for name, rows in SEED_ROWS.items()
        }
        self._export_files: list[dict[str, Any]] = deepcopy(SEED_EXPORT_FILES)
        # 导出动作需要「校验 → 写文件 → 改任务」整体原子，单进程内用锁串行化。
        self.lock = RLock()

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def find_by_code(self, module: str, field: str, code: str) -> dict[str, Any] | None:
        """按业务编号（任务编号、条目编号等）读取记录。"""
        target = str(code or "").strip()
        if not target:
            return None
        for row in self.rows(module):
            if str(row.get(field, "")).strip() == target:
                return row
        return None

    # ---- 分析导出文件 ----

    def export_files(self, task_no: str | None = None) -> list[dict[str, Any]]:
        """读取分析导出文件；按任务编号过滤时只可能返回一份（按编号去重）。"""
        files = self._export_files
        if task_no is not None:
            target = str(task_no).strip()
            files = [item for item in files if str(item.get("任务编号", "")).strip() == target]
        return files

    def replace_export_file(self, file: dict[str, Any]) -> dict[str, Any]:
        """按任务编号 upsert：先清掉该任务已有的全部文件，再写入当前这一份。

        这样重复开始同一导出只会保留一个分析导出文件，不会叠加出多份。
        """
        task_no = str(file.get("任务编号", "")).strip()
        self._export_files[:] = [
            item
            for item in self._export_files
            if str(item.get("任务编号", "")).strip() != task_no
        ]
        self._export_files.append(dict(file))
        return self._export_files[-1]

    def remove_export_files(self, task_no: str) -> None:
        target = str(task_no).strip()
        self._export_files[:] = [
            item
            for item in self._export_files
            if str(item.get("任务编号", "")).strip() != target
        ]

    def snapshot_export_files(self) -> list[dict[str, Any]]:
        return deepcopy(self._export_files)

    def restore_export_files(self, snapshot: list[dict[str, Any]]) -> None:
        self._export_files[:] = deepcopy(snapshot)

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
