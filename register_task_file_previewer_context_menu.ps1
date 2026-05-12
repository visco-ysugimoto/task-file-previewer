# Register right-click menu for TaskFilePreviewer (current user only)

param(
    [string]$AppPath = "",
    [switch]$IncludeZip
)

$ErrorActionPreference = "Stop"

function Resolve-AppPath {
    param([string]$InputPath)

    if ($InputPath) {
        if ([System.IO.Path]::IsPathRooted($InputPath)) {
            return (Resolve-Path $InputPath).Path
        }
        return (Resolve-Path (Join-Path $PSScriptRoot $InputPath)).Path
    }

    # Prefer the distributed EXE next to this script, then fallback to build outputs.
    $localExePath = Join-Path $PSScriptRoot "TaskFilePreviewer.exe"
    if (Test-Path $localExePath) {
        return (Resolve-Path $localExePath).Path
    }

    # Prefer OneDir build (faster startup), then fallback to OneFile.
    $defaultOneDirPath = Join-Path $PSScriptRoot "dist\TaskFilePreviewer\TaskFilePreviewer.exe"
    if (Test-Path $defaultOneDirPath) {
        return (Resolve-Path $defaultOneDirPath).Path
    }

    $defaultOneFilePath = Join-Path $PSScriptRoot "dist\TaskFilePreviewer.exe"
    if (Test-Path $defaultOneFilePath) {
        return (Resolve-Path $defaultOneFilePath).Path
    }

    throw "TaskFilePreviewer.exe was not found. Pass -AppPath explicitly."
}

function Register-ExtensionMenu {
    param(
        [string]$Extension,
        [string]$ExePath
    )

    $baseKey = "Registry::HKEY_CURRENT_USER\Software\Classes\SystemFileAssociations\$Extension\shell\TaskFilePreviewer"
    $commandKey = "$baseKey\command"
    # Script encoding differences can break Japanese literals on some environments.
    # Build the menu label from Unicode code points to keep it stable.
    $menuLabel = "TaskFilePreviewer $([char]0x3067)$([char]0x958B)$([char]0x304F)"
    # "%1" is quoted so paths with spaces are passed as a single argument.
    $commandValue = "`"$ExePath`" `"%1`""

    New-Item -Path $baseKey -Force | Out-Null
    Set-Item -Path $baseKey -Value $menuLabel
    New-ItemProperty -Path $baseKey -Name "Icon" -Value "$ExePath,0" -PropertyType String -Force | Out-Null

    New-Item -Path $commandKey -Force | Out-Null
    Set-Item -Path $commandKey -Value $commandValue
}

$exePath = Resolve-AppPath -InputPath $AppPath
if (-not (Test-Path $exePath)) {
    throw "App path does not exist: $exePath"
}

$extensions = @(".ziq", ".zit", ".zii")
if ($IncludeZip) {
    $extensions += ".zip"
}

foreach ($ext in $extensions) {
    Register-ExtensionMenu -Extension $ext -ExePath $exePath
}

Write-Host "Context menu registration completed." -ForegroundColor Green
Write-Host "Target app: $exePath" -ForegroundColor Cyan
Write-Host "Extensions: $($extensions -join ', ')" -ForegroundColor Cyan
