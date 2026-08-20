# LuminaForge install script
# Usage: powershell -ExecutionPolicy Bypass -File .\install.ps1

$ErrorActionPreference = "Stop"
Write-Host "LuminaForge Installer" -ForegroundColor Cyan
Write-Host "=====================`n"

$InstallDir = "$env:LOCALAPPDATA\Programs\LuminaForge"
$DesktopDir = [Environment]::GetFolderPath("Desktop")
$StartMenuDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\LuminaForge"
$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistDir = "$SourceDir\dist\LuminaForge.exe"

if (-not (Test-Path $DistDir)) {
    Write-Host "[ERROR] LuminaForge.exe not found. Please build first." -ForegroundColor Red
    Write-Host "  Build: venv\Scripts\pyinstaller luminaforge.spec --clean --noconfirm" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "[1/5] Stopping old instances..." -ForegroundColor Yellow
Get-Process -Name "LuminaForge" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

Write-Host "[2/5] Creating install directory..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Write-Host "       $InstallDir" -ForegroundColor Green

Write-Host "[3/5] Copying files..." -ForegroundColor Yellow
Copy-Item -Path $DistDir -Destination "$InstallDir\LuminaForge.exe" -Force
$LuminaForgeIcon = "$InstallDir\LuminaForge.ico"
if (Test-Path "$SourceDir\resources\luminaforge.ico") {
    Copy-Item -Path "$SourceDir\resources\luminaforge.ico" -Destination $LuminaForgeIcon -Force
} else {
    Remove-Item $LuminaForgeIcon -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Force -Path "$InstallDir\output" | Out-Null
New-Item -ItemType Directory -Force -Path "$InstallDir\jobs" | Out-Null
Write-Host "       Done" -ForegroundColor Green

Write-Host "[4/5] Creating desktop shortcut..." -ForegroundColor Yellow
Remove-Item "$DesktopDir\LuminaForge.lnk" -Force -ErrorAction SilentlyContinue
Remove-Item "$DesktopDir\墨影流光.lnk" -Force -ErrorAction SilentlyContinue
Remove-Item "$DesktopDir\Novel-to-Video.bat" -Force -ErrorAction SilentlyContinue

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$DesktopDir\墨影流光.lnk")
$Shortcut.TargetPath = "$InstallDir\LuminaForge.exe"
$Shortcut.IconLocation = if (Test-Path "$InstallDir\LuminaForge.ico") { "$InstallDir\LuminaForge.ico,0" } else { "$InstallDir\LuminaForge.exe,0" }
$Shortcut.Description = "LuminaForge - 字里乾坤 · 光影成诗"
$Shortcut.WorkingDirectory = "$InstallDir"
$Shortcut.Save()
Write-Host "       Desktop: 墨影流光.lnk" -ForegroundColor Green

Write-Host "[5/5] Creating start menu..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null

$StartShortcut = $WshShell.CreateShortcut("$StartMenuDir\墨影流光.lnk")
$StartShortcut.TargetPath = "$InstallDir\LuminaForge.exe"
$StartShortcut.IconLocation = if (Test-Path "$InstallDir\LuminaForge.ico") { "$InstallDir\LuminaForge.ico,0" } else { "$InstallDir\LuminaForge.exe,0" }
$StartShortcut.Description = "LuminaForge"
$StartShortcut.WorkingDirectory = "$InstallDir"
$StartShortcut.Save()

$UninstallShortcut = $WshShell.CreateShortcut("$StartMenuDir\Uninstall LuminaForge.lnk")
$UninstallShortcut.TargetPath = "$InstallDir\uninstall.ps1"
$UninstallShortcut.Description = "Uninstall LuminaForge"
$UninstallShortcut.Save()
Write-Host "       Start Menu: LuminaForge" -ForegroundColor Green

Copy-Item -Path "$SourceDir\uninstall.ps1" -Destination "$InstallDir\uninstall.ps1" -Force -ErrorAction SilentlyContinue

Write-Host "`nInstallation complete!" -ForegroundColor Green
Write-Host "  Desktop: 墨影流光 (double-click to launch)" -ForegroundColor White
Write-Host "  Start Menu: Search 'LuminaForge' or '墨影流光'" -ForegroundColor White
Write-Host "  Location: $InstallDir" -ForegroundColor White
Write-Host "`nNote: ComfyUI must be started separately." -ForegroundColor DarkYellow

Read-Host "Press Enter to finish"
