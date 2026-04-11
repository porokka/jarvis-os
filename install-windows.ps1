# ============================================================
# J.A.R.V.I.S OS — Windows Install Script
# Run in PowerShell as Administrator
# ============================================================

Write-Host ""
Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║     J.A.R.V.I.S — WINDOWS INSTALLER      ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

function Log($msg) { Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $msg" -ForegroundColor Gray }

# ── 1. Check prerequisites ───────────────────────────────────
Log "Checking prerequisites..."

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: winget not found. Install App Installer from Microsoft Store." -ForegroundColor Red
    exit 1
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Log "Installing Node.js..."
    winget install OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
}

# ── 2. Install Windows apps ─────────────────────────────────
Log "Installing mpv (audio player)..."
winget install shinchiro.mpv --accept-package-agreements --accept-source-agreements 2>$null

Log "Installing ffmpeg (audio processing)..."
winget install Gyan.FFmpeg --accept-package-agreements --accept-source-agreements 2>$null

# ── 3. Install WSL if needed ────────────────────────────────
$wslInstalled = Get-Command wsl -ErrorAction SilentlyContinue
if (-not $wslInstalled) {
    Log "Installing WSL2..."
    wsl --install -d Ubuntu
    Write-Host "WSL installed. REBOOT required, then run this script again." -ForegroundColor Yellow
    exit 0
}

# ── 4. Run WSL install ──────────────────────────────────────
$jarvisDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$wslPath = $jarvisDir -replace '\\', '/' -replace '^([A-Z]):', '/mnt/$1'.ToLower()

Log "Running WSL installer..."
wsl bash "$wslPath/install.sh"

# ── 5. Install Next.js app ──────────────────────────────────
Log "Installing Next.js HUD..."
Push-Location "$jarvisDir\app"
npm install
Pop-Location

# ── 6. Create .env.local for Next.js ────────────────────────
$envFile = "$jarvisDir\app\.env.local"
if (-not (Test-Path $envFile)) {
    Log "Creating .env.local..."
    @"
BRIDGE_URL=http://localhost:4000
TTS_URL=http://localhost:5100
"@ | Out-File -FilePath $envFile -Encoding utf8
}

# ── Done ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║     J.A.R.V.I.S INSTALLED (Windows)      ║" -ForegroundColor Green
Write-Host "║                                          ║" -ForegroundColor Green
Write-Host "║  Start (WSL terminal):                   ║" -ForegroundColor Green
Write-Host "║    bash jarvis.sh start                  ║" -ForegroundColor Green
Write-Host "║                                          ║" -ForegroundColor Green
Write-Host "║  Start HUD (PowerShell):                 ║" -ForegroundColor Green
Write-Host "║    cd app; npm run dev                   ║" -ForegroundColor Green
Write-Host "║    Open http://localhost:3000             ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Green
