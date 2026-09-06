// GeneratePage.tsx —— 生成页：选择题型、按 input_schema 动态渲染参数、发起生成
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { generate, getApiErrorMessage, listTemplates } from '../api/client'
import type { Template } from '../api/types'

interface FieldDef {
  name: string
  type: string
  enum?: string[]
  minimum?: number
  maximum?: number
  required: boolean
}

/** 从模板 input_schema 解析出可渲染的表单字段定义 */
function parseFields(template: Template): FieldDef[] {
  const schema = template.input_schema as Record<string, any>
  const props = (schema?.properties || {}) as Record<string, any>
  const required = new Set<string>(schema?.required || [])
  return Object.entries(props).map(([name, def]) => ({
    name,
    type: def?.type || 'string',
    enum: def?.enum,
    minimum: def?.minimum,
    maximum: def?.maximum,
    required: required.has(name),
  }))
}

/** 为字段生成默认值 */
function defaultValue(field: FieldDef): string | number {
  if (field.enum && field.enum.length > 0) return field.enum[0]
  if (field.type === 'integer') return field.minimum ?? 5
  return ''
}

export default function GeneratePage() {
  const navigate = useNavigate()

  const [templates, setTemplates] = useState<Template[]>([])
  const [templateId, setTemplateId] = useState('')
  const [values, setValues] = useState<Record<string, string | number>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // 当前选中模板的字段定义
  const fields = useMemo<FieldDef[]>(() => {
    const tpl = templates.find((t) => t.type_id === templateId)
    return tpl ? parseFields(tpl) : []
  }, [templates, templateId])

  // 加载题型模板
  useEffect(() => {
    listTemplates()
      .then((list) => {
        setTemplates(list)
        if (list.length > 0) setTemplateId(list[0].type_id)
      })
      .catch((e) => setError(getApiErrorMessage(e, '题型模板加载失败')))
  }, [])

  // 切换模板时重置表单值
  useEffect(() => {
    const next: Record<string, string | number> = {}
    fields.forEach((f) => {
      next[f.name] = defaultValue(f)
    })
    setValues(next)
  }, [templateId]) // eslint-disable-line react-hooks/exhaustive-deps

  const setField = (name: string, value: string | number) =>
    setValues((prev) => ({ ...prev, [name]: value }))

  /** 提交生成任务 */
  const handleSubmit = async () => {
    if (!templateId) {
      setError('请选择题型模板')
      return
    }
    // 校验必填字段
    for (const f of fields) {
      if (f.required && !String(values[f.name] ?? '').trim()) {
        setError(`请填写必填字段：${f.name}`)
        return
      }
    }
    setError('')
    setLoading(true)

    // 数字字段转 number
    const params: Record<string, unknown> = {}
    fields.forEach((f) => {
      const v = values[f.name]
      params[f.name] = f.type === 'integer' ? Number(v) : v
    })
    // 任务数量取自 quantity 字段（若存在），否则默认 1
    const quantity = Number(params.quantity ?? 1)

    try {
      const result = await generate({
        template_id: templateId,
        quantity,
        params,
      })
      navigate(`/tasks?task_id=${result.task_id}`)
    } catch (e) {
      setError(getApiErrorMessage(e, '发起生成失败'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page">
      <h2 className="page-title">生成内容</h2>
      <div className="card form-card">
        <div className="form-group">
          <label className="form-label">题型模板</label>
          <select
            className="form-control"
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value)}
          >
            {templates.length === 0 && <option value="">暂无可用模板</option>}
            {templates.map((t) => (
              <option key={t.type_id} value={t.type_id}>
                {t.name}（{t.type_id}）
              </option>
            ))}
          </select>
        </div>

        {fields.map((f) => (
          <div className="form-group" key={f.name}>
            <label className="form-label">
              {f.name}
              {f.required && <span className="required-mark"> *</span>}
            </label>
            {f.enum && f.enum.length > 0 ? (
              <select
                className="form-control"
                value={String(values[f.name] ?? '')}
                onChange={(e) => setField(f.name, e.target.value)}
              >
                {f.enum.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            ) : f.type === 'integer' ? (
              <input
                className="form-control"
                type="number"
                min={f.minimum}
                max={f.maximum}
                value={String(values[f.name] ?? '')}
                onChange={(e) => setField(f.name, Number(e.target.value) || 0)}
              />
            ) : (
              <input
                className="form-control"
                type="text"
                value={String(values[f.name] ?? '')}
                onChange={(e) => setField(f.name, e.target.value)}
              />
            )}
          </div>
        ))}

        {error && <div className="alert-error">{error}</div>}

        <div className="form-actions">
          <button
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={loading}
          >
            {loading ? '提交中…' : '开始生成'}
          </button>
        </div>
      </div>
    </div>
  )
}