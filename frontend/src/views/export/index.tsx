import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/export'
const columns = [
  "任务编号",
  "数据源名称",
  "导出格式",
  "字段选择",
  "筛选条件",
  "导出上限",
  "文件大小",
  "任务状态"
]
const actions = [
  "开始导出",
  "标记完成",
  "清理文件"
]
const statuses = [
  "草稿",
  "导出中",
  "已完成",
  "已过期"
]
const filterFields = ["任务编号", "数据源名称", "导出格式"]

type Row = Record<string, string | number | null>
type ExportFile = Record<string, string | number | null>

async function readPayload(response: Response): Promise<Record<string, unknown>> {
  return (await response.json().catch(() => ({}))) as Record<string, unknown>
}

export default function ExportView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [selected, setSelected] = useState<Row | null>(null)
  const selectedId = useRef<string | null>(null)
  const filterKeys = useMemo(() => filterFields, [])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('导出任务列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '分析导出中心列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  // 过滤后详情指向的任务已不在当前列表时收起详情，避免留下上一次的残留内容。
  useEffect(() => {
    if (selectedId.current !== null && !rows.some((row) => String(row.id) === selectedId.current)) {
      selectedId.current = null
      setSelected(null)
    }
  }, [rows])

  const stats = useMemo(() => {
    const exporting = rows.filter((row) => row.任务状态 === '导出中').length
    const finished = rows.filter((row) => row.任务状态 === '已完成').length
    return [
      { label: '导出任务总数', value: total },
      { label: '导出中任务', value: exporting },
      { label: '已完成任务', value: finished },
    ]
  }, [rows, total])

  /** 详情始终回后端读取，避免停留在上一次操作留下的旧值。 */
  const openDetail = useCallback(async (entryId: unknown) => {
    if (entryId == null) return
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${entryId}`)
      if (response.status === 404) {
        // 任务已不存在或被清理：不再显示残留详情。
        selectedId.current = null
        setSelected(null)
        setErrorMessage('该导出任务已不存在或已归档')
        return
      }
      if (!response.ok) throw new Error('导出详情读取失败')
      const payload = (await response.json()) as Row
      selectedId.current = String(payload.id)
      setSelected(payload)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '导出详情读取失败')
    }
  }, [])

  function closeDetail() {
    selectedId.current = null
    setSelected(null)
  }

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action } }),
      })
      const payload = await readPayload(response)
      // 后端用 { ok, message } 表达业务结果，动作被挡下时 HTTP 仍是 200。
      if (!response.ok || payload.ok === false) {
        throw new Error(String(payload.message ?? payload.detail ?? '分析导出中心动作未生效，请稍后重试'))
      }
      setNotice(String(payload.message ?? '操作已完成'))
      await reload()
      if (selectedId.current !== null && selectedId.current === String(row.id)) {
        await openDetail(row.id)
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '分析导出中心操作失败')
    }
  }

  /** 导出入口带页面此刻的过滤条件，返回整套任务而不是单条详情。 */
  function openExportEntry() {
    const query = new URLSearchParams(filters).toString()
    window.open(query ? `${ENDPOINT}/export?${query}` : `${ENDPOINT}/export`, '_blank')
  }

  async function downloadFile(row: Row) {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(`${ENDPOINT}/files/${row.任务编号 ?? row.id}`)
      const payload = await readPayload(response)
      if (!response.ok) {
        throw new Error(String(payload.detail ?? '该任务还没有分析导出文件，请先开始导出'))
      }
      const file = payload as ExportFile
      setNotice(`分析导出文件：${String(file.任务编号)}（字段选择 ${String(file.字段选择 ?? '—')}，${String(file.文件大小)} 字节）`)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '分析导出文件读取失败')
    }
  }

  const detailFiles = (selected?.分析导出文件 as ExportFile[] | undefined) ?? []

  return (
    <section className="page" data-module="export">
      <header className="page-head">
        <div>
          <h2>分析导出中心管理</h2>
          <p className="page-desc">维护分析导出的格式配置、字段选择与容量控制，为分析导出中心提供可验证的数据工程流程。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('导出任务登记入口尚未接入审批流')}>
            登记导出任务
          </button>
          <button className="btn" type="button" onClick={openExportEntry}>
            导出分析导出中心清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        {stats.map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        {filterKeys.map((field) => (
          <label key={field} className="filter-item">
            <span>{field}</span>
            <input
              value={filters[field] ?? ''}
              placeholder={`按${field}检索`}
              onChange={(event) => setFilters((prev) => ({ ...prev, [field]: event.target.value }))}
            />
          </label>
        ))}
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)} className={selected && String(selected.id) === String(row.id) ? 'row-active' : undefined}>
              {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
              <td className="row-actions">
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
                <button className="link" type="button" onClick={() => void openDetail(row.id)}>详情</button>
                <button className="link" type="button" onClick={() => void downloadFile(row)}>查看文件</button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 1}>暂无分析导出中心数据，可先登记导出任务</td>
            </tr>
          )}
        </tbody>
      </table>

      {selected && (
        <section className="detail-panel">
          <header className="detail-head">
            <h3>{String(selected.任务编号 ?? '')} · 导出详情</h3>
            <button className="btn ghost" type="button" onClick={closeDetail}>关闭</button>
          </header>
          <dl className="detail-grid">
            {columns.map((column) => (
              <div key={column} className="detail-item">
                <dt>{column}</dt>
                <dd>{selected[column] ?? '—'}</dd>
              </div>
            ))}
          </dl>
          <h4>分析导出文件</h4>
          {detailFiles.length === 0 ? (
            <p className="small-text">该任务还没有分析导出文件，执行「开始导出」后生成。</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr><th>任务编号</th><th>导出格式</th><th>字段选择</th><th>筛选条件</th><th>文件大小</th></tr>
              </thead>
              <tbody>
                {detailFiles.map((file) => (
                  <tr key={String(file.任务编号)}>
                    <td>{file.任务编号}</td>
                    <td>{file.导出格式}</td>
                    <td>{file.字段选择}</td>
                    <td>{file.筛选条件}</td>
                    <td>{file.文件大小}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      <footer className="page-foot">
        <span>共 {total} 条分析导出中心记录</span>
        {notice && <span className="notice-text">{notice}</span>}
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
