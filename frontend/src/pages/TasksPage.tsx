// TasksPage.tsx —— 任务页：任务列表、刷新、查看详情
import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getApiErrorMessage, getTask, listTasks } from '../api/client'
import type { GenerationTask } from '../api/types'

/** 任务状态中文标签 */
const STATUS_LABEL: Record<string, string> = {
  pending: '待执行',
  running: '执行中',
  partially_succeeded: '部分成功',
  succeeded: '已完成',
  failed: '失败',
}

/** 计算任务耗时（秒） */
function elapsedSeconds(task: GenerationTask): string {
  const start = new Date(task.created_at).getTime()
  const end = new Date(task.updated_at).getTime()
  if (Number.isNaN(start) || Number.isNaN(end)) return '-'
  const sec = Math.max(0, Math.round((end - start) / 1000))
  if (sec < 60) return `${sec} 秒`
  return `${Math.floor(sec / 60)} 分 ${sec % 60} 秒`
}

export default function TasksPage() {
  const [searchParams] = useSearchParams()
  const [tasks, setTasks] = useState<GenerationTask[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  // 详情弹窗
  const [detail, setDetail] = useState<GenerationTask | null>(null)

  const load = useCallback(async (p: number) => {
    setLoading(true)
    setError('')
    try {
      const res = await listTasks(p, 20)
      setTasks(res.items)
      setTotal(res.total)
    } catch (e) {
      setError(getApiErrorMessage(e, '任务列表加载失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(page)
    // 从生成页跳转过来时，自动打开对应任务详情
    const taskId = searchParams.get('task_id')
    if (taskId) {
      getTask(taskId)
        .then(setDetail)
        .catch(() => undefined)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, load])

  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  return (
    <div className="page">
      <div className="page-header">
        <h2 className="page-title">生成任务</h2>
        <button className="btn btn-primary" onClick={() => load(page)} disabled={loading}>
          刷新
        </button>
      </div>

      {error && <div className="alert-error">{error}</div>}

      <div className="card table-card">
        <table className="table">
          <thead>
            <tr>
              <th>任务 ID</th>
              <th>题型</th>
              <th>数量</th>
              <th>状态</th>
              <th>进度</th>
              <th>耗时</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <tr key={task.id}>
                <td className="mono">{task.id}</td>
                <td>{task.template_id}</td>
                <td>{task.quantity}</td>
                <td>
                  <span className={`status-tag status-${task.status}`}>
                    {STATUS_LABEL[task.status] ?? task.status}
                  </span>
                </td>
                <td>
                  <div className="progress">
                    <div className="progress-bar" style={{ width: `${task.progress}%` }} />
                  </div>
                  <span className="progress-text">{Math.round(task.progress)}%</span>
                </td>
                <td>{elapsedSeconds(task)}</td>
                <td>
                  <button className="btn btn-ghost" onClick={() => setDetail(task)}>
                    查看详情
                  </button>
                </td>
              </tr>
            ))}
            {tasks.length === 0 && (
              <tr>
                <td colSpan={7} className="empty">
                  {loading ? '加载中…' : '暂无任务'}
                </td>
              </tr>
            )}
          </tbody>
        </table>

        <div className="pagination">
          <span className="pagination-total">共 {total} 条</span>
          <button
            className="btn btn-ghost"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            上一页
          </button>
          <span>
            {page} / {totalPages}
          </span>
          <button
            className="btn btn-ghost"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            下一页
          </button>
        </div>
      </div>

      {/* 任务详情弹窗 */}
      {detail && (
        <div className="modal-mask" onClick={() => setDetail(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>任务详情</h3>
              <button className="btn btn-ghost" onClick={() => setDetail(null)}>
                关闭
              </button>
            </div>
            <div className="modal-body">
              <dl className="detail-list">
                <dt>任务 ID</dt>
                <dd className="mono">{detail.id}</dd>
                <dt>题型</dt>
                <dd>{detail.template_id}</dd>
                <dt>数量</dt>
                <dd>{detail.quantity}</dd>
                <dt>状态</dt>
                <dd>{STATUS_LABEL[detail.status] ?? detail.status}</dd>
                <dt>进度</dt>
                <dd>{Math.round(detail.progress)}%</dd>
                <dt>耗时</dt>
                <dd>{elapsedSeconds(detail)}</dd>
                <dt>参数</dt>
                <dd>
                  <pre className="pre">{JSON.stringify(detail.params, null, 2)}</pre>
                </dd>
              </dl>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}