$root = Split-Path -Parent $PSScriptRoot
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\demo-site'; python -m http.server 4173"
Write-Host 'Demo shop running at http://127.0.0.1:4173'
Write-Host 'Start the API and frontend with .\scripts\dev.ps1, then load the extension from chrome://extensions.'
