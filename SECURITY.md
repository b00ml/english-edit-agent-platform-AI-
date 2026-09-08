# Security Policy

## Supported Versions

当前主分支的最新公开版本受支持。

## Reporting a Vulnerability

请通过私下渠道报告安全问题，不要直接在公开 Issue 中贴出：

- API Key
- JWT Secret
- 数据库密码
- 用户隐私数据
- 真实生产日志

## Security Expectations

- 不要提交 .env 或任何真实密钥
- 不要把占位配置当成生产配置
- 不要把未验证的生产能力写进 README 或 Release Notes
- 若发现历史中泄露过密钥，应先吊销密钥，再清理历史
