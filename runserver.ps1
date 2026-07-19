#!/usr/bin/env pwsh
$projectRoot = Split-Path -Path $MyInvocation.MyCommand.Path -Parent
$venvActivate = Join-Path $projectRoot "venv\Scripts\Activate.ps1"
if (-Not (Test-Path $venvActivate)) {
    Write-Error "Virtual environment not found. Create one with: python -m venv venv"
    exit 1
}

Write-Host "Activating virtual environment..."
. $venvActivate

Write-Host "Installing dependencies if required..."
python -m pip install -r "$projectRoot\requirements.txt"

Write-Host "Starting Django development server..."
python "$projectRoot\manage.py" runserver
