# Installs a Windows Task Scheduler job that runs the engine every trading morning at 09:10.
# Run PowerShell as Administrator from the project root:
#   powershell -ExecutionPolicy Bypass -File scripts\install_windows_task.ps1

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BatPath = Join-Path $ProjectRoot "scripts\run_engine.bat"
$Action = New-ScheduledTaskAction -Execute $BatPath
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 9:10AM
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName "SVMKR_UT_HMA_Engine_0910" -Action $Action -Trigger $Trigger -Settings $Settings -Description "Starts SVMKR UT HMA Engine at 09:10 on weekdays. Engine itself skips configured holidays." -Force
Write-Host "Installed task: SVMKR_UT_HMA_Engine_0910"
