# LuminaForge uninstall script

$ErrorActionPreference = "Stop"
Write-Host "LuminaForge Uninstaller" -ForegroundColor Cyan
Write-Host "======================="

$InstallDir = "$env:LOCALAPPDATA\Programs\LuminaForge"
$DesktopDir = [Environment]::GetFolderPath("Desktop")
$StartMenuDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\LuminaForge"

Write-Host "[1/3] Stopping LuminaForge..." -ForegroundColor Yellow
Get-Process -Name "LuminaForge" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

Write-Host "[2/3] Cleaning shortcuts..." -ForegroundColor Yellow
Remove-Item "$DesktopDir\LuminaForge.lnk" -Force -ErrorAction SilentlyContinue
Remove-Item "$DesktopDir\墨影流光.lnk" -Force -ErrorAction SilentlyContinue
Remove-Item "$DesktopDir\Novel-to-Video.bat" -Force -ErrorAction SilentlyContinue
Remove-Item -Path "$StartMenuDir" -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "[3/3] Cleaning program files..." -ForegroundColor Yellow
$KeepData = Read-Host "Keep output, jobs and config files? (Y/n, default keep)"
if ($KeepData -eq "n" -or $KeepData -eq "N") {
    Remove-Item -Path "$InstallDir" -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "       Fully uninstalled" -ForegroundColor Green
} else {
    Get-ChildItem -Path "$InstallDir" -Exclude "output", "jobs", "launcher_config.json" -Recurse |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "       Program removed, user data kept at: $InstallDir" -ForegroundColor Yellow
}

Write-Host "`nUninstall complete." -ForegroundColor Green
Read-Host "Press Enter to exit"
