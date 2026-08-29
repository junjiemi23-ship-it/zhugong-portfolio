# Harness Smart Router 启动/停止/健康检查脚本（Windows）
# 用法: powershell -ExecutionPolicy Bypass -File harness_router.ps1 <start|stop|restart|status|health|test>
param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status", "health", "test")]
    [string]$Action = "status"
)

$RouterDir = Split-Path -Parent $PSScriptRoot
$Port = if ($env:HARNESS_ROUTER_PORT) { $env:HARNESS_ROUTER_PORT } else { 8124 }
$HealthUrl = "http://127.0.0.1:$Port/health"
$PidFile = Join-Path $RouterDir ".router.pid"
# 优先使用项目 venv 的 python（uv sync 产物），不存在时回退系统 python
$VenvPython = Join-Path $RouterDir ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
# Provider Key 兜底：进程环境缺失时从用户级环境变量补齐（Windows 下子进程常继承不到用户级新变量）
foreach ($KeyName in 'BAI_API_KEY', 'NVIDIA_API_KEY', 'GROQ_API_KEY') {
    if (-not [Environment]::GetEnvironmentVariable($KeyName)) {
        $UserVal = [Environment]::GetEnvironmentVariable($KeyName, 'User')
        if ($UserVal) { Set-Item -Path ("Env:" + $KeyName) -Value $UserVal }
    }
}

function Test-RouterRunning {
    try {
        $resp = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 3 -ErrorAction Stop
        return ($resp.status -eq "ok")
    } catch { return $false }
}

switch ($Action) {
    "start" {
        if (Test-RouterRunning) {
            Write-Host "[OK] Router already running on port $Port"
            exit 0
        }
        Write-Host "[..] Starting router on port $Port ..."
        $proc = Start-Process -FilePath $Python -ArgumentList "-m", "router.harness_router" `
            -WorkingDirectory $RouterDir -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $RouterDir "router.log") `
            -RedirectStandardError (Join-Path $RouterDir "router.err.log")
        Set-Content -Path $PidFile -Value $proc.Id
        Start-Sleep -Seconds 3
        if (Test-RouterRunning) {
            Write-Host "[OK] Router started (PID $($proc.Id))"
        } else {
            Write-Host "[FAIL] Router did not become healthy. Check router.err.log"
            exit 1
        }
    }
    "stop" {
        if (Test-Path $PidFile) {
            $pidToStop = Get-Content $PidFile
            try {
                Stop-Process -Id $pidToStop -Force -ErrorAction Stop
                Write-Host "[OK] Stopped PID $pidToStop"
            } catch { Write-Host "[WARN] PID $pidToStop not running" }
            Remove-Item $PidFile -ErrorAction SilentlyContinue
        }
        # 兜底：按端口找进程
        $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn) {
            Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
            Write-Host "[OK] Killed process on port $Port"
        } else {
            Write-Host "[OK] No process on port $Port"
        }
    }
    "restart" {
        # $MyInvocation.MyCommand.Path 在 -File 调用下为空（递归变空转挂死），必须用 $PSCommandPath
        & $PSCommandPath stop
        Start-Sleep -Seconds 2
        & $PSCommandPath start
    }
    "status" {
        if (Test-RouterRunning) { Write-Host "[RUNNING] port $Port" }
        else { Write-Host "[STOPPED] port $Port"; exit 1 }
    }
    "health" {
        try {
            Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 5 | ConvertTo-Json -Depth 5
        } catch {
            Write-Host "[FAIL] Health check failed: $_"
            exit 1
        }
    }
    "test" {
        Push-Location $RouterDir
        & $Python -m unittest tests.test_router -v
        Pop-Location
    }
}