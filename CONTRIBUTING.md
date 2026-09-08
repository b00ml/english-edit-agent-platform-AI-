# Contributing

## 开发前提

- Python 3.12
- Node.js 22+
- Docker Desktop
- PostgreSQL 16 + Redis

## 本地启动

后端：

~~~powershell
cd backend
$env:PYTHONPATH='.'
pytest -q -o addopts="" -m "not integration"
~~~

前端：

~~~powershell
cd frontend
npm ci
npm run build
~~~

## 提交要求

- 不提交真实密钥、数据库密码、用户数据、模型调用日志
- 备份脚本、临时修复脚本、日志文件不进入公开仓库
- 提交前先确认 git diff --cached --stat

## 代码规则

- 配置走环境变量，不硬编码模型名、数据库串和 API Key
- 模型输出必须经过服务端校验
- 变更应补充测试，尤其是工作流、结构化输出、权限和恢复逻辑
