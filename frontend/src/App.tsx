// App.tsx —— 应用外壳：登录守卫 + 左侧导航 + 右侧内容区
import { useEffect, useState } from 'react'
import { NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import GeneratePage from './pages/GeneratePage'
import TasksPage from './pages/TasksPage'
import QualityPage from './pages/QualityPage'
import ContentLibraryPage from './pages/ContentLibraryPage'
import CostsPage from './pages/CostsPage'
import NotificationsPage from './pages/NotificationsPage'
import TracePage from './pages/TracePage'
import DashboardPage from './pages/DashboardPage'
import SamplesPage from './pages/SamplesPage'
import KnowledgeBasePage from './pages/KnowledgeBasePage'
import UserManagePage from './pages/UserManagePage'
import LoginPage from './pages/LoginPage'
import { getUnreadCount } from './api/client'
import {
  clearAuth,
  getCurrentUser,
  hasPermission,
  isLoggedIn,
} from './api/auth'
import type { UserInfo } from './api/types'

/** 导航项配置（含权限点，无权限则不显示） */
const NAV_ITEMS = [
  { to: '/', label: '生成', end: true, permission: 'generate:create' },
  { to: '/tasks', label: '任务', end: false, permission: 'content:read' },
  { to: '/quality', label: '质检', end: false, permission: 'quality:review' },
  { to: '/library', label: '内容库', end: false, permission: 'content:read' },
  { to: '/samples', label: '样本库', end: false, permission: 'ops:read' },
  { to: '/knowledge', label: '知识库', end: false, permission: 'ops:read' },
  { to: '/dashboard', label: '看板', end: false, permission: 'ops:read' },
  { to: '/costs', label: '成本', end: false, permission: 'ops:read' },
  { to: '/traces', label: '链路', end: false, permission: 'ops:read' },
  { to: '/notifications', label: '消息', end: false, permission: null },
  { to: '/users', label: '用户管理', end: false, permission: 'user:manage' },
]

const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  researcher: '教研员',
  reviewer: '质检员',
  viewer: '查看者',
}

export default function App() {
  const [unread, setUnread] = useState(0)
  const [user, setUser] = useState<UserInfo | null>(() => getCurrentUser())
  const location = useLocation()
  const navigate = useNavigate()

  const loggedIn = isLoggedIn()

  // 未登录时重定向到登录页
  useEffect(() => {
    if (!loggedIn && location.pathname !== '/login') {
      navigate('/login', { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loggedIn, location.pathname])

  // 轮询未读通知数（登录后每 30s）
  useEffect(() => {
    if (!loggedIn) return
    let alive = true
    const poll = () => {
      getUnreadCount()
        .then((r) => alive && setUnread(r.count))
        .catch(() => undefined)
    }
    poll()
    const timer = setInterval(poll, 30000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [loggedIn])

  // 登录页：独立布局，不渲染侧边栏
  if (!loggedIn) {
    return (
      <Routes>
        <Route path="*" element={<LoginPage />} />
      </Routes>
    )
  }

  const visibleNav = NAV_ITEMS.filter(
    (item) => item.permission === null || hasPermission(item.permission),
  )

  const handleLogout = () => {
    clearAuth()
    setUser(null)
    navigate('/login', { replace: true })
  }

  return (
    <div className="layout">
      {/* 左侧侧边栏导航 */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-logo">E</span>
          <span className="brand-name">英语内容编辑工作台</span>
        </div>
        <nav className="sidebar-nav">
          {visibleNav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                isActive ? 'nav-item active' : 'nav-item'
              }
            >
              {item.label}
              {item.to === '/notifications' && unread > 0 && (
                <span className="nav-badge">{unread}</span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="sidebar-user">
            <span className="sidebar-user-name">{user?.display_name || user?.username}</span>
            <span className="status-tag">
              {user ? ROLE_LABELS[user.role] ?? user.role : ''}
            </span>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={handleLogout}>
            退出登录
          </button>
        </div>
      </aside>

      {/* 右侧内容区 */}
      <main className="content">
        <Routes>
          <Route path="/" element={<GeneratePage />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/quality" element={<QualityPage />} />
          <Route path="/library" element={<ContentLibraryPage />} />
          <Route path="/samples" element={<SamplesPage />} />
          <Route path="/knowledge" element={<KnowledgeBasePage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/costs" element={<CostsPage />} />
          <Route path="/traces" element={<TracePage />} />
          <Route path="/notifications" element={<NotificationsPage />} />
          <Route path="/users" element={<UserManagePage />} />
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </main>
    </div>
  )
}
