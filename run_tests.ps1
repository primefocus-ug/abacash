#!/usr/bin/env powershell
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

Write-Host "Testing loans app..." -ForegroundColor Green
Write-Host "Working directory: $(Get-Location)"
Write-Host ""

# Set environment
$env:PYTHONUNBUFFERED = '1'
$env:DJANGO_SETTINGS_MODULE = 'config.settings'

# Run tests
Write-Host "Running: python manage.py test loans -v 2" -ForegroundColor Cyan
& python manage.py test loans -v 2

$exitCode = $LASTEXITCODE
Write-Host ""
Write-Host "Test execution completed with exit code: $exitCode" -ForegroundColor $(if($exitCode -eq 0) { "Green" } else { "Red" })

# Compile Python files
Write-Host ""
Write-Host "Compiling Python files..." -ForegroundColor Green
$files = @('loans\utils.py', 'loans\tests.py')
foreach ($file in $files) {
    if (Test-Path $file) {
        python -m py_compile $file
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ $file compiled" -ForegroundColor Green
        } else {
            Write-Host "✗ $file failed compilation" -ForegroundColor Red
        }
    }
}

exit $exitCode
