"""导出入口 / 任务登记 / 目录读取调用链回归（不依赖 pytest/httpx）。"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("EXPORT_TEST_BASE", "http://127.0.0.1:8014")
FAILURES: list[str] = []


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8") or "{}"
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, {"raw": raw}


def q(**params) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL {name} {detail}")


def main() -> int:
    print("== 导出入口不再被单条详情截获 ==")
    status, body = call("GET", "/api/export/export")
    check("导出入口 HTTP 200", status == 200, str(status))
    check("导出入口返回整套任务", body.get("module") == "export" and isinstance(body.get("items"), list))
    check("导出入口含 EXPO-0001..0003", {"EXPO-0001", "EXPO-0002", "EXPO-0003"} <= {i["任务编号"] for i in body["items"]})

    status, detail = call("GET", "/api/export/EXPO-0002")
    check("按任务编号读详情", status == 200 and detail.get("任务编号") == "EXPO-0002", str(status))

    print("== 导出入口按页面过滤条件返回整套任务 ==")
    status, filtered = call("GET", "/api/export/export?" + q(**{"任务编号": "EXPO-0002"}))
    check("导出入口按任务编号过滤", status == 200 and filtered.get("total") == 1, str(filtered))
    check("过滤结果不是单条详情", "module" in filtered and "items" in filtered)
    status, by_src = call("GET", "/api/export/export?" + q(**{"数据源名称": "商品"}))
    check("导出入口按数据源名称过滤", by_src.get("total") == 1 and by_src["items"][0]["任务编号"] == "EXPO-0002")
    status, by_fmt = call("GET", "/api/export/export?" + q(**{"导出格式": "Parquet"}))
    check("导出入口按导出格式过滤", by_fmt.get("total") == 1)

    print("== 列表页与导出入口字段口径一致 ==")
    status, listed = call("GET", "/api/export?" + q(status="导出中"))
    listed_row = next(i for i in listed["items"] if i["任务编号"] == "EXPO-0002")
    entry_row = next(i for i in body["items"] if i["任务编号"] == "EXPO-0002")
    for field in ("字段选择", "筛选条件", "导出上限", "导出格式"):
        check(f"列表与入口 {field} 一致", listed_row[field] == entry_row[field], f"{listed_row[field]} != {entry_row[field]}")

    print("== 登记带字段选择与筛选条件 ==")
    status, created = call("POST", "/api/export", {"values": {
        "任务编号": "EXPO-8001",
        "数据源名称": "订单明细数据集",
        "导出格式": "CSV",
        "字段选择": "order_id,order_amount",
        "筛选条件": "amount>=100",
        "导出上限": "500",
    }})
    entry = created.get("entry") or {}
    check("登记成功", created.get("ok") is True, str(created))
    check("字段选择落库", entry.get("字段选择") == "order_id,order_amount", str(entry.get("字段选择")))
    check("筛选条件落库", entry.get("筛选条件") == "amount>=100", str(entry.get("筛选条件")))
    check("导出上限落库", entry.get("导出上限") == "500", str(entry.get("导出上限")))
    status, reread = call("GET", "/api/export/EXPO-8001")
    check("详情与登记一致", reread.get("字段选择") == "order_id,order_amount" and reread.get("筛选条件") == "amount>=100")

    print("== 目录能核对导出文件引用的字段清单 ==")
    status, dataset = call("GET", "/api/catalog/fields/" + urllib.parse.quote("订单明细数据集"))
    check("按数据集名称读字段清单", status == 200 and "order_id" in (dataset.get("字段") or []), str(dataset))
    catalog_fields = set(dataset.get("字段") or [])
    export_fields = {f.strip() for f in reread.get("字段选择", "").split(",") if f.strip()}
    check("导出字段都在目录字段清单内", export_fields <= catalog_fields, f"{export_fields - catalog_fields}")
    status, cat_export = call("GET", "/api/catalog/export")
    check("目录导出入口可用", status == 200 and cat_export.get("module") == "catalog")

    print("== 重复开始同一导出只保留一个分析导出文件 ==")
    status, first = call("POST", "/api/export/EXPO-8001/actions", {"values": {"action": "开始导出"}})
    check("首次开始导出成功", first.get("ok") is True, str(first))
    status, files1 = call("GET", "/api/export/files")
    count1 = sum(1 for f in files1["items"] if f["任务编号"] == "EXPO-8001")
    check("首次生成一份文件", count1 == 1, str(count1))
    status, second = call("POST", "/api/export/EXPO-8001/actions", {"values": {"action": "开始导出"}})
    check("重复开始导出成功", second.get("ok") is True, str(second))
    status, files2 = call("GET", "/api/export/files")
    count2 = sum(1 for f in files2["items"] if f["任务编号"] == "EXPO-8001")
    check("重复开始仍只有一份文件", count2 == 1, str(count2))
    status, one_file = call("GET", "/api/export/files/EXPO-8001")
    check("文件字段选择与任务一致",
          one_file.get("字段选择") == reread.get("字段选择"), str(one_file.get("字段选择")))

    print("== 导出失败时文件大小与任务状态一起回退 ==")
    status, bad = call("POST", "/api/export", {"values": {
        "任务编号": "EXPO-8002",
        "数据源名称": "订单明细数据集",
        "导出格式": "CSV",
        "字段选择": "order_id",
        "筛选条件": "无",
        "导出上限": "0",
    }})
    before = call("GET", "/api/export/EXPO-8002")[1]
    status, failed = call("POST", "/api/export/EXPO-8002/actions", {"values": {"action": "开始导出"}})
    after = call("GET", "/api/export/EXPO-8002")[1]
    check("非法导出上限被拦下", failed.get("ok") is False, str(failed))
    check("失败后任务状态回退", after.get("任务状态") == before.get("任务状态"), f"{before.get('任务状态')} -> {after.get('任务状态')}")
    check("失败后文件大小回退", after.get("文件大小") == before.get("文件大小"), f"{before.get('文件大小')} -> {after.get('文件大小')}")
    check("失败不留分析导出文件", call("GET", "/api/export/files/EXPO-8002")[0] == 404)

    print("== 历史任务缺少字段选择按目录补齐 ==")
    status, legacy = call("POST", "/api/export", {"values": {
        "任务编号": "EXPO-8003",
        "数据源名称": "门店流量数据集",
        "导出格式": "CSV",
    }})
    legacy_entry = legacy.get("entry", {})
    check("缺少字段选择时登记仍成功", legacy.get("ok") is True, str(legacy.get("message")))
    check("补齐字段选择", bool(legacy_entry.get("字段选择")), str(legacy_entry.get("字段选择")))
    status, legacy_detail = call("GET", "/api/export/EXPO-8003")
    status, legacy_list = call("GET", "/api/export?" + q(keyword="EXPO-8003"))
    listed_legacy = next((i for i in legacy_list["items"] if i["任务编号"] == "EXPO-8003"), {})
    check("列表与详情同一份补齐结果",
          listed_legacy.get("字段选择") == legacy_detail.get("字段选择") == legacy_entry.get("字段选择"),
          f"{listed_legacy.get('字段选择')} / {legacy_detail.get('字段选择')}")
    check("补齐取数据目录字段清单", legacy_detail.get("字段选择") == "store_id,visitor_cnt,gmv",
          str(legacy_detail.get("字段选择")))

    print("== 目录详情稳定：反复进入不残留、不重复 ==")
    for _ in range(3):
        status, cat_detail = call("GET", "/api/catalog/CATA-0002")
        check("目录详情可读", status == 200, str(status))
        check("字段清单唯一", isinstance(cat_detail.get("字段清单"), str))
    check("目录详情按编号与按 id 一致",
          call("GET", "/api/catalog/CATA-0002")[1] == call("GET", "/api/catalog/2")[1])

    print("== EXPO-0001..0003 导出格式 / 字段选择 / 导出上限 列表与入口一致 ==")
    for task_no in ("EXPO-0001", "EXPO-0002", "EXPO-0003"):
        status, one = call("GET", "/api/export/export?" + q(**{"任务编号": task_no}))
        found = [i for i in one["items"] if i["任务编号"] == task_no]
        check(f"{task_no} 在导出入口出现", len(found) == 1, str(found))
        if not found:
            continue
        listed = next((i for i in body["items"] if i["任务编号"] == task_no), {})
        row = found[0]
        for field in ("导出格式", "字段选择", "导出上限"):
            check(f"{task_no} {field} 列表与入口一致", listed.get(field) == row.get(field),
                  f"{listed.get(field)} != {row.get(field)}")
        check(f"{task_no} 字段选择非空", bool(str(row.get("字段选择") or "").strip()))

    print("== 各模块导出入口均可用 ==")
    for module in ("mart", "sqlpad", "vizdrag", "collab", "anomaly", "model", "opt", "story",
                   "etl", "catalog", "sample", "compare", "alarm", "refresh", "audit"):
        status, payload = call("GET", f"/api/{module}/export")
        check(f"{module} 导出入口 200", status == 200 and "items" in payload, f"{status} {payload}")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} 项失败：{', '.join(FAILURES)}")
        return 1
    print("全部回归通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
