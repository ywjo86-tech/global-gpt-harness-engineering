param(
    [string]$RepoUrl = "https://github.com/ywjo86-tech/global-gpt-harness-engineering.git",
    [string]$InstallRoot = "$env:USERPROFILE\Documents\AI-Workspace",
    [string]$FolderName = "global-gpt-harness-engineering",
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Require-Command {
    param([string]$Name)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "'$Name' command was not found. Install Git for Windows first, then run this installer again."
    }
}

Write-Step "Checking prerequisites"
Require-Command "git"

$installRootFull = [System.IO.Path]::GetFullPath($InstallRoot)
$targetPath = [System.IO.Path]::GetFullPath((Join-Path $installRootFull $FolderName))

Write-Step "Preparing install folder"
New-Item -ItemType Directory -Force -Path $installRootFull | Out-Null

if (Test-Path $targetPath) {
    $gitDir = Join-Path $targetPath ".git"
    if (-not (Test-Path $gitDir)) {
        throw "Target folder already exists but is not a Git repository: $targetPath"
    }

    Write-Step "Updating existing global harness"
    Push-Location $targetPath
    try {
        git fetch origin $Branch
        git checkout $Branch
        git pull --ff-only origin $Branch
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Step "Cloning global harness"
    git clone --branch $Branch $RepoUrl $targetPath
}

Write-Step "Verifying harness files"
$requiredPaths = @(
    "AGENTS.md",
    ".agents",
    "docs\harness",
    "templates"
)

$missing = @()
foreach ($relativePath in $requiredPaths) {
    $fullPath = Join-Path $targetPath $relativePath
    if (-not (Test-Path $fullPath)) {
        $missing += $relativePath
    }
}

if ($missing.Count -gt 0) {
    throw "Install completed but required harness paths are missing: $($missing -join ', ')"
}

Write-Host ""
Write-Host "Global harness installed successfully." -ForegroundColor Green
Write-Host "Path: $targetPath"
Write-Host ""
Write-Host "Open this folder in Codex, then test with:"
Write-Host "현재 전역하네스에서 사용 가능한 스킬과 새 프로젝트 오케스트레이터를 요약해줘. 파일 수정 없이 확인만 해줘."
Write-Host ""
Write-Host "To start a new project, use:"
Write-Host "새 프로젝트 시작"
