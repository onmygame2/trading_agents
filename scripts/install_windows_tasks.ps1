param(
    [string]$TaskPrefix = "TradingAgents",
    [string]$VenvPath = "venv_akshare"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Runner = Join-Path $Root "scripts\run_with_venv.ps1"
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$LegacyDailyTask = "$TaskPrefix-DailyRun"
if (Get-ScheduledTask -TaskName $LegacyDailyTask -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $LegacyDailyTask -Confirm:$false
    Write-Host "Removed legacy task $LegacyDailyTask"
}

function Register-QuantTask {
    param(
        [string]$Name,
        [string]$Time,
        [string]$ArgsLine,
        [string]$LogName,
        [switch]$FridayOnly
    )
    $FullName = "$TaskPrefix-$Name"
    $LogPath = Join-Path $LogDir $LogName
    $ActionArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`" $ArgsLine *>> `"$LogPath`""
    $Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $ActionArgs -WorkingDirectory $Root
    $Days = if ($FridayOnly) { @("Friday") } else { @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday") }
    $Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Days -At $Time
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $FullName -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null
    Write-Host "Registered $FullName at $Time -> $ArgsLine"
}

Register-QuantTask -Name "KlineUpdate" -Time "08:30" -ArgsLine "update_kline.py --snapshot" -LogName "kline_update.log"
$IntradayTimes = @("09:30", "10:00", "10:30", "11:00", "11:30", "13:00", "13:30", "14:00", "14:30", "15:00")
foreach ($Time in $IntradayTimes) {
    $Suffix = $Time.Replace(":", "")
    Register-QuantTask -Name "DailyRun$Suffix" -Time $Time -ArgsLine "daily_runner_v2.py" -LogName "intraday.log"
}
Register-QuantTask -Name "AgentReview" -Time "15:15" -ArgsLine "main.py agent review" -LogName "agent_review.log"
Register-QuantTask -Name "WeeklyOptimize" -Time "20:00" -ArgsLine "optimize_weekly.py" -LogName "weekly_opt.log" -FridayOnly

Write-Host "Windows scheduled tasks installed with prefix: $TaskPrefix"
