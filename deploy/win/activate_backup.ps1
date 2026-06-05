# Helper script to activate daily QATrack+ database backups via Windows Task Scheduler
$ErrorActionPreference = "Stop"

# Automatically find QATrack+ root directory based on the location of this script
$script_dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$qatrack_dir = Split-Path -Parent $script_dir

Write-Host "QATrack+ Directory detected as: $qatrack_dir"

$manage_py = Join-Path $qatrack_dir "manage.py"
if (-Not (Test-Path $manage_py)) {
    Write-Error "manage.py not found in $qatrack_dir. Are you running this script from the deploy/win/ directory?"
    exit
}

$confirmation = Read-Host "This script will create a Windows Scheduled Task ('QATrackBackup') to run 'python manage.py backup_site' daily at 2:00 AM. Do you want to proceed? (y/n)"
if ($confirmation -ne 'y') {
    Write-Host "Aborted."
    exit
}

# Assume python is available in the venv
$python_exe = "python"
$venv_python = Join-Path $qatrack_dir "venv\Scripts\python.exe"
if (Test-Path $venv_python) {
    $python_exe = $venv_python
} else {
    $env_python = Join-Path $qatrack_dir "env\Scripts\python.exe"
    if (Test-Path $env_python) {
        $python_exe = $env_python
    }
}

$taskName = "QATrackBackup"

# Remove existing task if it exists
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "Removing existing scheduled task '$taskName'..."
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

Write-Host "Creating new scheduled task '$taskName'..."

$action = New-ScheduledTaskAction -Execute $python_exe -Argument "manage.py backup_site" -WorkingDirectory $qatrack_dir
$trigger = New-ScheduledTaskTrigger -Daily -At 2:00AM
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Description "Daily QATrack+ Database Backup"

Write-Host "Successfully registered Scheduled Task '$taskName'."
Write-Host "The backup command will run every day at 2:00 AM under the SYSTEM account."
