// UserManagePage.tsx —— 用户管理页（仅管理员）：新建/改角色/重置密码/禁用
import { useCallback, useEffect, useState } from 'react'
import { createUser, getApiErrorMessage, listUsers, updateUser } from '../api/client'
import type { UserInfo } from '../api/types'

const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  researcher: '教研员',
  reviewer: '质检员',
  viewer: '查看者',
}

const ROLE_OPTIONS = [
  { value: 'admin', label: '管理员' },
  { value: 'researcher', label: '教研员' },
  { value: 'reviewer', label: '质检员' },
  { value: 'viewer', label: '查看者' },
]

const PAGE_SIZE = 20

/** 空表单初值 */
const EMPTY_FORM = { username: '', password: '', display_name: '', role: 'viewer' }

export default function UserManagePage() {
  const [items, setItems] = useState<UserInfo[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  // 新建弹窗
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)

  // 改角色/密码/禁用
  const [editing, setEditing] = useState<UserInfo | null>(null)
  const [editRole, setEditRole] = useState('viewer')
  const [editPassword, setEditPassword] = useState('')
  const [editSaving, setEditSaving] = useState(false)

  const load = useCallback((p: number) => {
    setLoading(true)
    setError('')
    listUsers(p, PAGE_SIZE)
      .then((r) => {
        setItems(r.items)
        setTotal(r.total)
      })
      .catch((e) => setError(getApiErrorMessage(e, '用户加载失败')))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load(1)
  }, [load])

  const handleCreate = () => {
    setSaving(true)
    setError('')
    createUser(form)
      .then(() => {
        setSuccess(`用户 ${form.username} 创建成功`)
        setShowCreate(false)
        setForm(EMPTY_FORM)
        load(1)
      })
      .catch((e) => setError(getApiErrorMessage(e, '创建失败')))
      .finally(() => setSaving(false))
  }

  const handleEditSave = () => {
    if (!editing) return
    setEditSaving(true)
    setError('')
    const patch: { role?: string; password?: string; status?: string } = {}
    if (editRole !== editing.role) patch.role = editRole
    if (editPassword) patch.password = editPassword
    updateUser(editing.id, patch)
      .then(() => {
        setSuccess('用户已更新')
        setEditing(null)
        setEditPassword('')
        load(page)
      })
      .catch((e) => setError(getApiErrorMessage(e, '更新失败')))
      .finally(() => setEditSaving(false))
  }

  const handleToggleStatus = (u: UserInfo) => {
    const next = u.status === 'active' ? 'disabled' : 'active'
    updateUser(u.id, { status: next })
      .then(() => {
        setSuccess(next === 'active' ? '已启用用户' : '已禁用用户')
        load(page)
      })
      .catch((e) => setError(getApiErrorMessage(e, '操作失败')))
  }

  return (
    <div className="page">
      <div className="page-header">
        <h2 className="page-title">用户管理</h2>
        <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
          新建用户
        </button>
      </div>

      {error && <div className="alert-error">{error}</div>}
      {success && <div className="alert-success">{success}</div>}

      <div className="card table-card">
        <div className="table-toolbar">
          <div className="table-count">共 {total} 个用户</div>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>用户名</th>
              <th>显示名</th>
              <th>角色</th>
              <th>状态</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((u) => (
              <tr key={u.id}>
                <td className="mono">{u.username}</td>
                <td>{u.display_name}</td>
                <td>
                  <span className="status-tag status-running">
                    {ROLE_LABELS[u.role] ?? u.role}
                  </span>
                </td>
                <td>
                  <span className={`status-tag ${u.status === 'active' ? 'status-succeeded' : 'status-rejected'}`}>
                    {u.status === 'active' ? '启用' : '禁用'}
                  </span>
                </td>
                <td className="mono">
                  {new Date(u.created_at).toLocaleString('zh-CN', { hour12: false })}
                </td>
                <td>
                  <div className="header-actions">
                    <button
                      className="btn-link-danger"
                      onClick={() => {
                        setEditing(u)
                        setEditRole(u.role)
                        setEditPassword('')
                      }}
                    >
                      编辑
                    </button>
                    <button
                      className="btn-link-danger"
                      onClick={() => handleToggleStatus(u)}
                    >
                      {u.status === 'active' ? '禁用' : '启用'}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  {loading ? '加载中…' : '暂无用户'}
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

      {/* 新建用户弹窗 */}
      {showCreate && (
        <div className="modal-mask" onClick={() => setShowCreate(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>新建用户</h3>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowCreate(false)}>
                关闭
              </button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label className="form-label">用户名</label>
                <input
                  className="form-control"
                  value={form.username}
                  onChange={(e) => setForm({ ...form, username: e.target.value })}
                  placeholder="登录用户名"
                />
              </div>
              <div className="form-group">
                <label className="form-label">密码</label>
                <input
                  className="form-control"
                  type="password"
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  placeholder="至少 6 位"
                />
              </div>
              <div className="form-group">
                <label className="form-label">显示名</label>
                <input
                  className="form-control"
                  value={form.display_name}
                  onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                  placeholder="选填"
                />
              </div>
              <div className="form-group">
                <label className="form-label">角色</label>
                <select
                  className="form-control"
                  value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value })}
                >
                  {ROLE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-actions">
                <button className="btn btn-primary" onClick={handleCreate} disabled={saving}>
                  {saving ? '创建中…' : '创建'}
                </button>
                <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>
                  取消
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 编辑用户弹窗 */}
      {editing && (
        <div className="modal-mask" onClick={() => setEditing(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>编辑用户 · {editing.username}</h3>
              <button className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>
                关闭
              </button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label className="form-label">角色</label>
                <select
                  className="form-control"
                  value={editRole}
                  onChange={(e) => setEditRole(e.target.value)}
                >
                  {ROLE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">重置密码（留空不改）</label>
                <input
                  className="form-control"
                  type="password"
                  value={editPassword}
                  onChange={(e) => setEditPassword(e.target.value)}
                  placeholder="至少 6 位"
                />
              </div>
              <div className="form-actions">
                <button className="btn btn-primary" onClick={handleEditSave} disabled={editSaving}>
                  {editSaving ? '保存中…' : '保存'}
                </button>
                <button className="btn btn-ghost" onClick={() => setEditing(null)}>
                  取消
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
