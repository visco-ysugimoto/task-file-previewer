# Build TaskFilePreviewer for distribution
param(
    [ValidateSet("OneDir", "OneFile")]
    [string]$BuildMode = "OneDir"
)

$ErrorActionPreference = "Stop"

Push-Location $PSScriptRoot
try {
Write-Host "=== Build TaskFilePreviewer ===" -ForegroundColor Cyan
Write-Host "Build mode: $BuildMode" -ForegroundColor Cyan
Write-Host ""

$appVersionFile = ".\app_version.txt"
$appVersion = ""
if (Test-Path $appVersionFile) {
    $appVersion = (Get-Content $appVersionFile | Select-Object -First 1).Trim()
}
if (-not $appVersion) {
    $appVersion = "0.0.0"
}
$safeAppVersion = $appVersion -replace '[^0-9A-Za-z._-]', '_'
Write-Host "App version: $safeAppVersion" -ForegroundColor Cyan
Write-Host ""

if (Test-Path ".\venv") {
    Write-Host "Activating venv..." -ForegroundColor Yellow
    .\venv\Scripts\Activate.ps1
} elseif (Test-Path ".\.venv") {
    Write-Host "Activating .venv..." -ForegroundColor Yellow
    .\.venv\Scripts\Activate.ps1
}

Write-Host "Installing dependencies..." -ForegroundColor Yellow
python -m pip install --upgrade pip
python -m pip install -r .\requirements_task_file_previewer.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to install dependencies." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Generating Windows version resource..." -ForegroundColor Yellow
python .\build_file_version_info.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to generate file_version_info.txt." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Cleaning previous build artifacts..." -ForegroundColor Yellow
if (Test-Path ".\build\TaskFilePreviewer") { Remove-Item -Recurse -Force ".\build\TaskFilePreviewer" }
if (Test-Path ".\dist\TaskFilePreviewer.exe") { Remove-Item -Force ".\dist\TaskFilePreviewer.exe" }
if (Test-Path ".\dist\TaskFilePreviewer") { Remove-Item -Recurse -Force ".\dist\TaskFilePreviewer" }
Get-ChildItem ".\dist" -Filter "TaskFilePreviewer_portable*.zip" -ErrorAction SilentlyContinue | Remove-Item -Force

Write-Host ""
Write-Host "Running PyInstaller..." -ForegroundColor Green
$specPath = if ($BuildMode -eq "OneDir") { ".\TaskFilePreviewer_onedir.spec" } else { ".\TaskFilePreviewer.spec" }
python -m PyInstaller $specPath --noconfirm --clean
if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed. Check logs above." -ForegroundColor Red
    exit 1
}

$exePath = if ($BuildMode -eq "OneDir") { ".\dist\TaskFilePreviewer\TaskFilePreviewer.exe" } else { ".\dist\TaskFilePreviewer.exe" }
if (-not (Test-Path $exePath)) {
    Write-Host "EXE not found: $exePath" -ForegroundColor Red
    exit 1
}

if ($BuildMode -eq "OneDir") {
    Write-Host "Copying helper files for distribution..." -ForegroundColor Yellow
    $distDir = (Resolve-Path ".\dist\TaskFilePreviewer").Path
    $helperFiles = @(
        ".\icon_image.ico",
        ".\app_version.txt",
        ".\app.manifest",
        ".\README.md",
        ".\distribution_guide.md",
        ".\register_task_file_previewer_context_menu.bat",
        ".\register_task_file_previewer_context_menu_include_zip.bat",
        ".\register_task_file_previewer_context_menu.ps1",
        ".\unregister_task_file_previewer_context_menu.bat",
        ".\unregister_task_file_previewer_context_menu_include_zip.bat",
        ".\unregister_task_file_previewer_context_menu.ps1"
    )
    foreach ($helperFile in $helperFiles) {
        if (Test-Path $helperFile) {
            Copy-Item -Path $helperFile -Destination $distDir -Force
        }
    }
}

$zipBaseName = if ($BuildMode -eq "OneDir") {
    "TaskFilePreviewer_portable_onedir_v$safeAppVersion.zip"
} else {
    "TaskFilePreviewer_portable_v$safeAppVersion.zip"
}
$zipPath = ".\dist\$zipBaseName"
Write-Host "Creating portable ZIP..." -ForegroundColor Yellow
if (Test-Path $zipPath) {
    Remove-Item -Force $zipPath
}

$zipCreated = $false
$lastZipError = ""
for ($i = 1; $i -le 5; $i++) {
    try {
        if ($BuildMode -eq "OneDir") {
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            [System.IO.Compression.ZipFile]::CreateFromDirectory(
                (Resolve-Path ".\dist\TaskFilePreviewer").Path,
                (Resolve-Path ".\dist").Path + "\" + [System.IO.Path]::GetFileName($zipPath),
                [System.IO.Compression.CompressionLevel]::Optimal,
                $false
            )
        } else {
            Compress-Archive -Path $exePath -DestinationPath $zipPath -Force
        }
        $zipCreated = Test-Path $zipPath
        if ($zipCreated) {
            break
        }
    } catch {
        $lastZipError = $_.Exception.Message
        Start-Sleep -Milliseconds 700
    }
}

if (-not $zipCreated) {
    Write-Host "Failed to create ZIP after retries." -ForegroundColor Red
    if ($lastZipError) {
        Write-Host "ZIP error: $lastZipError" -ForegroundColor Red
    }
    exit 1
}

$exeFile = Get-Item $exePath
$zipFile = Get-Item $zipPath

Write-Host ""
Write-Host "=== Build succeeded ===" -ForegroundColor Green
Write-Host "EXE: $exePath" -ForegroundColor Cyan
Write-Host "ZIP: $zipPath" -ForegroundColor Cyan
Write-Host "EXE size: $([math]::Round($exeFile.Length / 1MB, 2)) MB" -ForegroundColor Gray
Write-Host "ZIP size: $([math]::Round($zipFile.Length / 1MB, 2)) MB" -ForegroundColor Gray
if ($BuildMode -eq "OneDir") {
    Write-Host "Note: OneDir starts faster than OneFile." -ForegroundColor Gray
}
}
finally {
    Pop-Location
}
