<#
.SYNOPSIS
  One-time setup of the chatbot service on Windows.

.DESCRIPTION
  Creates chatbot-service\.venv with Python 3.12 or 3.13, installs the packages,
  and downloads the E-Branchformer speech model (~0.4 GB) and the embedding model
  (~0.1 GB) into the Hugging Face cache (%USERPROFILE%\.cache\huggingface).
  Safe to run again: finished steps are skipped by pip.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File setup.ps1          # everything (~3 GB with PyTorch)
  powershell -ExecutionPolicy Bypass -File setup.ps1 -Light   # tests and widget work only, no models
#>
param([switch]$Light)

$ErrorActionPreference = 'Stop'
$service = Join-Path $PSScriptRoot 'chatbot-service'
$venv = Join-Path $service '.venv'
$python = Join-Path $venv 'Scripts\python.exe'

function Invoke-Checked {
	param([string]$Exe, [string[]]$Arguments)
	& $Exe @Arguments
	if ($LASTEXITCODE -ne 0) { throw "Failed: $Exe $($Arguments -join ' ')" }
}

function Test-SupportedPython {
	param([string[]]$Command)
	try {
		$exe, $rest = $Command
		& $exe @rest -c 'import sys; sys.exit(0 if sys.version_info[:2] in ((3, 12), (3, 13)) else 1)' 2>$null
		return $LASTEXITCODE -eq 0
	} catch {
		return $false
	}
}

if ((Test-Path $python) -and -not (Test-SupportedPython @($python))) {
	throw "chatbot-service\.venv uses an unsupported Python version. Delete that folder and run setup.ps1 again."
}

if (-not (Test-Path $python)) {
	# ESPnet supports Python 3.12 and 3.13 only (not 3.11, not 3.14).
	$candidates = @(@('py', '-3.13'), @('py', '-3.12'), @('python3.13'), @('python3.12'), @('python'))
	$base = $candidates | Where-Object { Test-SupportedPython $_ } | Select-Object -First 1
	if (-not $base) {
		throw 'Python 3.12 or 3.13 is required. Install Python 3.13 from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then run setup.ps1 again.'
	}
	Write-Host "Creating chatbot-service\.venv with: $($base -join ' ')"
	$exe, $rest = $base
	Invoke-Checked $exe ($rest + @('-m', 'venv', $venv))
}

Invoke-Checked $python @('-m', 'pip', 'install', '--upgrade', 'pip')
Invoke-Checked $python @('-m', 'pip', 'install', '-r', (Join-Path $service 'requirements-dev.txt'))

if (-not $Light) {
	# CPU-only PyTorch first, so pip does not pull the much larger CUDA build.
	Invoke-Checked $python @('-m', 'pip', 'install', '--index-url', 'https://download.pytorch.org/whl/cpu', 'torch==2.11.*', 'torchaudio==2.11.*')
	Invoke-Checked $python @('-m', 'pip', 'install', '-r', (Join-Path $service 'requirements-ml.txt'))
	Push-Location $service
	try {
		Invoke-Checked $python @('scripts\download_models.py')
	} finally {
		Pop-Location
	}
}

Write-Host ''
Write-Host 'Setup complete. Next:' -ForegroundColor Green
Write-Host '  cd chatbot-service'
Write-Host '  .venv\Scripts\activate          (cmd)   or   .venv\Scripts\Activate.ps1   (PowerShell)'
Write-Host '  pytest'
if ($Light) {
	Write-Host '  python scripts\dev_server.py --fake-asr "how can i volunteer"'
} else {
	Write-Host '  python scripts\dev_server.py'
}
