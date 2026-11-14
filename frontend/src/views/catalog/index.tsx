import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/catalog'
const columns = [
  "条目编号",
  "数据集名称",
  "业务域",
  "字段清单",
  "更新频率",
  "数据等级",
  "负责人",
  "条目状态"
]
const actions = [
  "发布条目",
  "下线条目",
  "归档条目"
]
const statuses = [
  "草稿",
  "已发布",
  "已下线",
  "已归档"
]
const stats = [
  {
    "label": "目录条目总数",
    "value": 0
  },
  {
    "label": "已发布条目",
    "value": 0
  },
  {
    "label": "已下线条目",
    "value": 0
  }
]

const filterFields = ["条目编号", "数据集名称", "业务域"]

type Row = Record<string, string | number | null>

export default function CatalogView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [selected, setSelected] = useState<Row | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const filterKeys = useMemo(() => filterFields, [])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('目录条目列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '数据目录检索列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  // 过滤后详情指向的条目已不在当前列表时收起详情，避免留下上一次的残留内容。
  useEffect(() => {
    if (selectedId !== null && !rows.some((row) => String(row.id) === selectedId)) {
      setSelected(null)
      setSelectedId(null)
    }
  }, [rows, selectedId])

  /** 详情每次回后端读取，不沿用上一次的选中内容，避免残留旧字段清单。 */
  const openDetail = useCallback(async (entryId: unknown) => {
    if (entryId == null) return
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(`${ENDPOINT}/${entryId}`)
      if (response.status === 404) {
        // 条目已不存在：立即收起详情，不留下上一次的内容。
        setSelected(null)
        setSelectedId(null)
        setErrorMessage('该目录条目已不存在或已归档')
        return
      }
      if (!response.ok) throw new Error('目录条目详情读取失败')
      const payload = (await response.json()) as Row
      setSelected(payload)
      setSelectedId(String(payload.id))
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '目录条目详情读取失败')
    }
  }, [])

  function closeDetail() {
    setSelected(null)
    setSelectedId(null)
  }

  function openExportEntry() {
    const query = new URLSearchParams(filters).toString()
    window.open(query ? `${ENDPOINT}/export?${query}` : `${ENDPOINT}/export`, '_blank')
  }

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action } }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload.ok === false) {
        throw new Error(String(payload.message ?? payload.detail ?? '数据目录检索动作未生效，请稍后重试'))
      }
      setNotice(String(payload.message ?? '操作已完成'))
      await reload()
      if (selectedId !== null && selectedId === String(row.id)) {
        await openDetail(row.id)
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '数据目录检索操作失败')
    }
  }

  return (
    <section className="page" data-module="catalog">
      <header className="page-head">
        <div>
          <h2>数据目录检索管理</h2>
          <p className="page-desc">维护数据目录的业务域归属、字段清单与等级标识，为数据目录检索提供可追溯的数据工程流程。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('目录条目登记入口尚未接入审批流')}>
            登记目录条目
          </button>          <button className="btn" type="button" onClick={openExportEntry}>
            导出数据目录检索清单
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
            <tr key={String(row.id)} className={selectedId === String(row.id) ? 'row-active' : undefined}>
              {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
              <td className="row-actions">
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
                <button className="link" type="button" onClick={() => void openDetail(row.id)}>详情</button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 1}>暂无数据目录检索数据，可先登记目录条目</td>
            </tr>
          )}
        </tbody>
      </table>

      {selected && (
        <section className="detail-panel">
          <header className="detail-head">
            <h3>{String(selected.条目编号 ?? '')} · 目录详情</h3>
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
        </section>
      )}

      <footer className="page-foot">
        <span>共 {total} 条数据目录检索记录</span>
        {notice && <span className="notice-text">{notice}</span>}
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
