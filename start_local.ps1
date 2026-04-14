$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw 'Environnement Python introuvable: .venv\Scripts\python.exe'
}

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollama) {
    Start-Process -FilePath $ollama.Source -ArgumentList 'serve' -WindowStyle Hidden -ErrorAction SilentlyContinue | Out-Null
    Write-Host 'Ollama détecté - moteur LLM local prêt.'
} else {
    Write-Host 'Ollama non encore installé - le bot restera en attente côté IA.'
}

Start-Process -FilePath $python -ArgumentList 'control_panel.py','8765' -WorkingDirectory $PSScriptRoot | Out-Null
& $python 'run_bot.py' 'daemon'
