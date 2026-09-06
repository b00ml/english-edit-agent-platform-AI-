// NotificationsPage.tsx —— 站内消息通知页：查看/标记已读/全部已读
import { useEffect, useState } from 'react'
import {
  getApiErrorMessage,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from '../api/client'
import type { Notification } from '../api/types'

const TYPE_LABELS: Record<string, string> = {
  task_succeeded: '任务完成',
  task_partial: '部分成功',
  task_failed: '任务失败',
  content_rejected: '内容驳回',
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { hour12: false })
}

const PAGE_SIZE = 20

export default function NotificationsPage() {
  const [items, setItems] = useState<Notification[]>([])
  const [total, setTotal] = useState(0)
  const [unread, setUnread] = useState(0)
  const [page, setPage] = useState(1)
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = (p: number = page, onlyUnread: boolean = unreadOnly) => {
    setLoading(true)
    setError('')
    listNotifications({ unread_only: onlyUnread, page: p, page_size: PAGE_SIZE })
      .then((r) => {
        setItems(r.items)
        setTotal(r.total)
        setUnread(r.unread)
      })
      .catch((e) => setError(getApiErrorMessage(e, '通知加载失败')))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load(1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unreadOnly])

  const handleRead = (n: Notification) => {
    if (n.is_read) return
    markNotificationRead(n.id)
      .then(() => load())
      .catch((e) => setError(getApiErrorMessage(e, '操作失败')))
  }

  const handleReadAll = () => {
    markAllNotificationsRead()
      .then(() => load())
      .catch((e) => setError(getApiErrorMessage(e, '操作失败')))
  }

  return (
    <div className="page">
      <div className="page-header">
        <h2 className="page-title">站内消息{unread > 0 && `（未读 ${unread}）`}</h2>
        <button
          className="btn btn-ghost"
          onClick={handleReadAll}
          disabled={unread === 0}
        >
          全部已读
        </button>
      </div>

      {error && <div className="alert-error">{error}</div>}

      <div className="card filter-bar">
        <div className="form-group">
          <label className="form-label">消息类型</label>
          <select
            className="form-control"
            value={unreadOnly ? 'unread' : 'all'}
            onChange={(e) => setUnreadOnly(e.target.value === 'unread')}
          >
            <option value="all">全部消息</option>
            <option value="unread">仅未读</option>
          </select>
        </div>
      </div>

      <div className="card table-card">
        <table className="table">
          <thead>
            <tr>
              <th>类型</th>
              <th>标题</th>
              <th>内容</th>
              <th>时间</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {items.map((n) => (
              <tr
                key={n.id}
                onClick={() => handleRead(n)}
                style={{ cursor: n.is_read ? 'default' : 'pointer' }}
              >
                <td>
                  <span className="status-tag status-running">
                    {TYPE_LABELS[n.type] ?? n.type}
                  </span>
                </td>
                <td>{n.title}</td>
                <td>{n.content}</td>
                <td className="mono">{formatTime(n.created_at)}</td>
                <td>
                  {n.is_read ? (
                    <span className="status-tag">已读</span>
                  ) : (
                    <span className="status-tag status-succeeded">未读</span>
                  )}
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={5} className="empty">
                  {loading ? '加载中…' : '暂无消息'}
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
            onClick={() => {
              setPage(page - 1)
              load(page - 1)
            }}
          >
            上一页
          </button>
          <button
            className="btn btn-ghost"
            disabled={page * PAGE_SIZE >= total}
            onClick={() => {
              setPage(page + 1)
              load(page + 1)
            }}
          >
            下一页
          </button>
        </div>
      </div>
    </div>
  )
}