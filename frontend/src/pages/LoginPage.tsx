// LoginPage.tsx —— 登录页：账号密码登录，成功后进入工作台
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getApiErrorMessage, login } from '../api/client'

export default function LoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!username || !password) {
      setError('请输入用户名和密码')
      return
    }
    setLoading(true)
    setError('')
    login(username, password)
      .then(() => navigate('/', { replace: true }))
      .catch((err) => setError(getApiErrorMessage(err, '登录失败')))
      .finally(() => setLoading(false))
  }

  return (
    <div className="login-page">
      <form className="card login-card" onSubmit={handleSubmit}>
        <div className="login-brand">
          <span className="brand-logo">E</span>
          <span className="brand-name">英语内容编辑工作台</span>
        </div>
        <p className="login-sub">请登录以继续使用</p>

        {error && <div className="alert-error">{error}</div>}

        <div className="form-group">
          <label className="form-label">用户名</label>
          <input
            className="form-control"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            placeholder="请输入用户名"
          />
        </div>
        <div className="form-group">
          <label className="form-label">密码</label>
          <input
            className="form-control"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            placeholder="请输入密码"
          />
        </div>

        <button className="btn btn-primary login-btn" type="submit" disabled={loading}>
          {loading ? '登录中…' : '登录'}
        </button>
      </form>
    </div>
  )
}
