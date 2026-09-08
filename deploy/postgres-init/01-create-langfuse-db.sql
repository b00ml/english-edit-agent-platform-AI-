-- Langfuse 使用独立数据库；Postgres 只在数据卷首次初始化时执行本文件。
-- 数据库已存在时幂等跳过，避免重启破坏数据。
SELECT 'CREATE DATABASE langfuse'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec
