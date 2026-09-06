// KnowledgeBasePage.tsx —— 知识库：上传教研文档（试卷/练习册等）建立 RAG 知识库，浏览/检索/删除
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  deleteKnowledge,
  getApiErrorMessage,
  listKnowledge,
  retrieveKnowledge,
  uploadKnowledgeFile,
} from '../api/client'
import type { KnowledgeChunk } from '../api/types'

const SOURCE_TYPES = ['教材', '课标', '真题', '练习册', '其他']

const SOURCE_TYPE_OPTIONS = SOURCE_TYPES.map((s) => ({ value: s, label: s }))

export default function KnowledgeBasePage() {
  const [chunks, setChunks] = useState<KnowledgeChunk[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  // 筛选
  const [filterType, setFilterType] = useState('')
  // 上传
  const [sourceType, setSourceType] = useState('真题')
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // 检索
  const [query, setQuery] = useState('')
  const [snippets, setSnippets] = useState<string[]>([])
  const [searching, setSearching] = useState(false)

  const load = useCallback(
    async (p: number) => {
      setLoading(true)
      setError('')
      try {
        const res = await listKnowledge({
          source_type: filterType || undefined,
          page: p,
          page_size: 20,
        })
        setChunks(res.items)
        setTotal(res.total)
      } catch (e) {
        setError(getApiErrorMessage(e, '知识库加载失败'))
      } finally {
        setLoading(false)
      }
    },
    [filterType],
  )

  useEffect(() => {
    load(page)
  }, [load, page])

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null
    setFile(f)
    setError('')
    setSuccess('')
  }

  const handleUpload = async () => {
    if (!file) {
      setError('请先选择要上传的文件')
      return
    }
    setUploading(true)
    setError('')
    setSuccess('')
    try {
      const res = await uploadKnowledgeFile(file, sourceType)
      setSuccess(`已上传「${file.name}」并索引 ${res.chunks} 个分块`)
      setFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
      setPage(1)
      await load(1)
    } catch (e) {
      setError(getApiErrorMessage(e, '文件上传失败'))
    } finally {
      setUploading(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!window.confirm('确认删除该知识分块？')) return
    try {
      await deleteKnowledge(id)
      setSuccess('已删除')
      await load(page)
    } catch (e) {
      setError(getApiErrorMessage(e, '删除失败'))
    }
  }

  const handleSearch = async () => {
    if (!query.trim()) return
    setSearching(true)
    setError('')
    try {
      const res = await retrieveKnowledge(query.trim())
      setSnippets(res.snippets)
    } catch (e) {
      setError(getApiErrorMessage(e, '检索失败'))
    } finally {
      setSearching(false)
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / 20))

  return (
    <div className="page">
      <div className="page-header">
        <h2 className="page-title">RAG 知识库</h2>
      </div>

      {error && <div className="alert-error">{error}</div>}
      {success && <div className="alert-success">{success}</div>}

      {/* 文件上传 */}
      <div className="card">
        <h3 className="section-title">上传教研文档</h3>
        <div className="filter-bar">
          <div className="form-group">
            <label className="form-label">资料类型</label>
            <select
              className="form-control"
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value)}
            >
              {SOURCE_TYPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div className="form-group form-group-grow">
            <label className="form-label">文件（txt / md / docx / pdf）</label>
            <input
              ref={fileInputRef}
              className="form-control"
              type="file"
              accept=".txt,.md,.docx,.pdf"
              onChange={handleFileChange}
            />
          </div>
          <button
            className="btn btn-primary"
            onClick={handleUpload}
            disabled={uploading}
          >
            {uploading ? '上传中…' : '上传并索引'}
          </button>
        </div>
        <p className="hint">支持上传试卷、练习册、讲义等教研文档，系统将解析并分块向量化入库，供生成时按知识点检索引用。</p>
      </div>

      {/* 检索 */}
      <div className="card">
        <h3 className="section-title">检索测试</h3>
        <div className="filter-bar">
          <div className="form-group form-group-grow">
            <input
              className="form-control"
              placeholder="输入检索问题，查看命中的知识片段…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
          <button className="btn" onClick={handleSearch} disabled={searching}>
            {searching ? '检索中…' : '检 索'}
          </button>
        </div>
        {snippets.length > 0 && (
          <div className="snippet-list">
            {snippets.map((s, i) => (
              <div key={i} className="snippet-item">
                {s}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 分块列表 */}
      <div className="card table-card">
        <div className="table-toolbar">
          <div className="form-group">
            <label className="form-label">资料类型筛选</label>
            <select
              className="form-control"
              value={filterType}
              onChange={(e) => {
                setFilterType(e.target.value)
                setPage(1)
              }}
            >
              <option value="">全部</option>
              {SOURCE_TYPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <span className="table-count">共 {total} 个分块</span>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>来源</th>
              <th>类型</th>
              <th>知识点</th>
              <th>内容</th>
              <th>入库时间</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {chunks.map((c) => (
              <tr key={c.id}>
                <td className="mono">{c.source_name}</td>
                <td>{c.source_type}</td>
                <td>{c.knowledge_point ?? '-'}</td>
                <td className="cell-clamp">{c.content}</td>
                <td>{new Date(c.created_at).toLocaleString()}</td>
                <td>
                  <button className="btn-link-danger" onClick={() => handleDelete(c.id)}>
                    删除
                  </button>
                </td>
              </tr>
            ))}
            {chunks.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  {loading ? '加载中…' : '暂无知识分块，请先上传文档'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
        {totalPages > 1 && (
          <div className="pagination">
            <button
              className="btn"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              上一页
            </button>
            <span>
              {page} / {totalPages}
            </span>
            <button
              className="btn"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            >
              下一页
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
