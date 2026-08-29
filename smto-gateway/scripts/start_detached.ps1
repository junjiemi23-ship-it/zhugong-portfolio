$RouterDir = "C:\Users\mjj\AppData\Local\hermes\skills\software-development\harness-smart-router"
$Python = Join-Path $RouterDir ".venv\Scripts\python.exe"
foreach ($KeyName in 'BAI_API_KEY', 'NVIDIA_API_KEY', 'GROQ_API_KEY') {
    if (-not [Environment]::GetEnvironmentVariable($KeyName)) {
        $UserVal = [Environment]::GetEnvironmentVariable($KeyName, 'User')
        if ($UserVal) { Set-Item -Path ("Env:" + $KeyName) -Value $UserVal }
    }
}
# 429 冷却时间从 30s 提到 180s（NVIDIA 持续限流，2026-08-29）
$env:HARNESS_COOLDOWN_RATE_LIMITED = "180"
$proc = Start-Process -FilePath $Python -ArgumentList "-m", "router.harness_router" `
    -WorkingDirectory $RouterDir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $RouterDir "router.log") `
    -RedirectStandardError (Join-Path $RouterDir "router.err.log")
Set-Content -Path (Join-Path $RouterDir ".router.pid") -Value $proc.Id
Write-Output "Started PID $($proc.Id)"