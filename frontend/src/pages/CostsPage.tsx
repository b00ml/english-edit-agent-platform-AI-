// CostsPage.tsx —— 成本页：多维聚合 + 深度成本报表（生成/质检阶段拆分 + token 细分 + 单条下钻）
import { useEffect, useState } from 'react'
import { getApiErrorMessage, getCostDeep, getCosts, listTemplates } from '../api/client'
import type { CostByKey, CostDeepResult, CostRow, CostStage, Template } from '../api/types'

type GroupBy = 'template' | 'model' | 'task'

const GROUP_OPTIONS: { value: GroupBy; label: string }[] = [
  { value: 'template', label: '按题型' },
  { value: 'model', label: '按模型' },
  { value: 'task', label: '按任务' },
]

const STAGE_LABEL: Record<string, string> = {
  generate: '生成',
  qc: '质检',
  unknown: '未知',
}

function formatCost(v: number): string {
  return `¥${v.toFixed(4)}`
}

function formatTokens(v: number): string {
  return v.toLocaleString()
}

function formatMs(v?: number | null): string {
  return v == null ? '-' : `${v.toFixed(0)}ms`
}

export default function CostsPage() {
  const [rows, setRows] = useState<CostRow[]>([])
  const [groupBy, setGroupBy] = useState<GroupBy>('template')
  const [templates, setTemplates] = useState<Template[]>([])
  const [templateId, setTemplateId] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  // 深度成本报表数据
  const [deep, setDeep] = useState<CostDeepResult | null>(null)
  // 手动刷新触发器
  const [refreshKey, setRefreshKey] = useState(0)

  // 加载题型列表用于筛选
  useEffect(() => {
    listTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]))
  }, [])

  // 维度/题型变化或手动刷新时重新加载成本与深度报表
  useEffect(() => {
    setLoading(true)
    setError('')
    getCosts(groupBy, templateId || undefined)
      .then(setRows)
      .catch((e) => setError(getApiErrorMessage(e, '成本数据加载失败')))
      .then(() => getCostDeep({ template_id: templateId || undefined }))
      .then(setDeep)
      .catch((e) => setError(getApiErrorMessage(e, '深度成本报表加载失败')))
      .finally(() => setLoading(false))
  }, [groupBy, templateId, refreshKey])

  return (
    <div className="page">
      <div className="page-header">
        <h2 className="page-title">成本统计</h2>
        <button
          className="btn btn-primary"
          onClick={() => setRefreshKey((k) => k + 1)}
          disabled={loading}
        >
          刷 新
        </button>
      </div>

      {error && <div className="alert-error">{error}</div>}

      <div className="card filter-bar">
        <div className="form-group">
          <label className="form-label">聚合维度</label>
          <select
            className="form-control"
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value as GroupBy)}
          >
            {GROUP_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div className="form-group">
          <label className="form-label">题型筛选</label>
          <select
            className="form-control"
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value)}
          >
            <option value="">全部题型</option>
            {templates.map((t) => (
              <option key={t.type_id} value={t.type_id}>
                {t.name}（{t.type_id}）
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="card table-card">
        <table className="table">
          <thead>
            <tr>
              <th>维度</th>
              <th>调用次数</th>
              <th>总成本</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                <td className="mono">{row.name}</td>
                <td>{row.count}</td>
                <td>{formatCost(row.total_cost)}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={3} className="empty">
                  {loading ? '加载中…' : '暂无成本数据'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* 深度成本报表（K2）：阶段拆分 / token 细分 / 多维聚合 / 单条下钻 */}
      {deep && (
        <>
          {/* 汇总 */}
          <div className="card">
            <h3 className="section-title">深度成本汇总</h3>
            <div className="kpi-grid">
              <div className="kpi-card">
                <div className="kpi-value">{formatCost(deep.total_cost)}</div>
                <div className="kpi-label">总成本</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-value">{deep.total_count}</div>
                <div className="kpi-label">总调用次数</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-value">{formatTokens(deep.total_tokens)}</div>
                <div className="kpi-label">总 token</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-value">{formatTokens(deep.total_prompt_tokens)}</div>
                <div className="kpi-label">输入 token</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-value">{formatTokens(deep.total_completion_tokens)}</div>
                <div className="kpi-label">输出 token</div>
              </div>
            </div>
          </div>

          {/* 生成/质检阶段拆分 */}
          <div className="card table-card">
            <h3 className="section-title">按调用阶段拆分（生成 / 质检）</h3>
            <table className="table">
              <thead>
                <tr>
                  <th>阶段</th>
                  <th>调用次数</th>
                  <th>输入 token</th>
                  <th>输出 token</th>
                  <th>输入成本</th>
                  <th>输出成本</th>
                  <th>总成本</th>
                </tr>
              </thead>
              <tbody>
                {deep.stages.map((s: CostStage) => (
                  <tr key={s.stage}>
                    <td>
                      <span
                        className={`status-tag ${s.stage === 'qc' ? 'status-pending' : 'status-published'}`}
                      >
                        {STAGE_LABEL[s.stage] ?? s.stage}
                      </span>
                    </td>
                    <td>{s.count}</td>
                    <td>{formatTokens(s.prompt_tokens)}</td>
                    <td>{formatTokens(s.completion_tokens)}</td>
                    <td>{formatCost(s.prompt_cost)}</td>
                    <td>{formatCost(s.completion_cost)}</td>
                    <td>{formatCost(s.total_cost)}</td>
                  </tr>
                ))}
                {deep.stages.length === 0 && (
                  <tr>
                    <td colSpan={7} className="empty">
                      暂无阶段数据
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* 多维聚合 */}
          <CostByKeyCard title="按题型聚合" rows={deep.by_template} />
          <CostByKeyCard title="按模型聚合" rows={deep.by_model} />
          <CostByKeyCard title="按任务聚合" rows={deep.by_task} />

          {/* 单条下钻 */}
          <div className="card table-card">
            <h3 className="section-title">单条调用下钻（最近 {deep.traces.length} 条）</h3>
            <table className="table">
              <thead>
                <tr>
                  <th>trace_id</th>
                  <th>阶段</th>
                  <th>模型</th>
                  <th>题型</th>
                  <th>输入/输出 token</th>
                  <th>耗时</th>
                  <th>成本</th>
                </tr>
              </thead>
              <tbody>
                {deep.traces.map((t) => (
                  <tr key={t.trace_id + t.created_at + (t.model ?? '')}>
                    <td className="mono">{t.trace_id}</td>
                    <td>
                      <span
                        className={`status-tag ${t.stage === 'qc' ? 'status-pending' : 'status-published'}`}
                      >
                        {STAGE_LABEL[t.stage] ?? t.stage}
                      </span>
                    </td>
                    <td className="mono">{t.model ?? '-'}</td>
                    <td className="mono">{t.template_id ?? '-'}</td>
                    <td>
                      {(t.prompt_tokens ?? 0).toLocaleString()} /{' '}
                      {(t.completion_tokens ?? 0).toLocaleString()}
                    </td>
                    <td>{formatMs(t.latency_ms)}</td>
                    <td>{formatCost(t.cost ?? 0)}</td>
                  </tr>
                ))}
                {deep.traces.length === 0 && (
                  <tr>
                    <td colSpan={7} className="empty">
                      暂无调用明细
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

/** 按维度聚合的表（题型/模型/任务） */
function CostByKeyCard({ title, rows }: { title: string; rows: CostByKey[] }) {
  return (
    <div className="card table-card">
      <h3 className="section-title">{title}</h3>
      <table className="table">
        <thead>
          <tr>
            <th>维度</th>
            <th>调用次数</th>
            <th>输入 token</th>
            <th>输出 token</th>
            <th>总成本</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name}>
              <td className="mono">{r.name}</td>
              <td>{r.count}</td>
              <td>{formatTokens(r.prompt_tokens)}</td>
              <td>{formatTokens(r.completion_tokens)}</td>
              <td>{formatCost(r.total_cost)}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={5} className="empty">
                暂无数据
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
