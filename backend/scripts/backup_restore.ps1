param(
    [Parameter(Mandatory = $true)][ValidateSet("backup", "restore")][string]$Mode,
    [Parameter(Mandatory = $true)][string]$DatabaseUrl,
    [Parameter(Mandatory = $true)][string]$File,
    [string]$TargetDatabaseUrl
)

$ErrorActionPreference = "Stop"

if ($Mode -eq "backup") {
    pg_dump --format=custom --no-owner --no-privileges --file $File $DatabaseUrl
    Write-Host "backup_created=$File"
    exit 0
}

if ([string]::IsNullOrWhiteSpace($TargetDatabaseUrl)) {
    throw "restore 模式必须显式提供 -TargetDatabaseUrl"
}
if ($TargetDatabaseUrl -eq $DatabaseUrl) {
    throw "拒绝将备份恢复到源数据库；请指定独立目标库"
}
if (-not (Test-Path -LiteralPath $File -PathType Leaf)) {
    throw "备份文件不存在: $File"
}

# 不使用 --clean/--create，避免覆盖现有对象；目标库需由运维提前创建并验收。
pg_restore --exit-on-error --no-owner --no-privileges --dbname=$TargetDatabaseUrl $File
Write-Host "restore_completed=$TargetDatabaseUrl"
