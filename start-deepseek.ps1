# The key is held only in this process environment and inherited by the Python backend.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $env:DEEPSEEK_API_KEY) {
    $jdSecureKey = Read-Host 'Enter DEEPSEEK_API_KEY (hidden, not saved)' -AsSecureString
    $jdKeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($jdSecureKey)
    try {
        $env:DEEPSEEK_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($jdKeyPointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($jdKeyPointer)
        $jdSecureKey.Dispose()
    }
}
if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
    Write-Host 'No key provided. AI JD creation will be unavailable; manual entry still works.'
}
& (Join-Path $PSScriptRoot 'start.ps1')
