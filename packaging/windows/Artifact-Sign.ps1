# Signing-node adapter only. Requires a configured, validated signing account.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$File)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
foreach ($name in @('VISION_SIGNTOOL','VISION_SIGNING_DLIB','VISION_SIGNING_METADATA')) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if (-not $value -or -not (Test-Path -LiteralPath $value -PathType Leaf)) { throw 'signing_node_not_configured' }
}
& $env:VISION_SIGNTOOL sign /fd SHA256 /tr http://timestamp.acs.microsoft.com /td SHA256 `
    /dlib $env:VISION_SIGNING_DLIB /dmdf $env:VISION_SIGNING_METADATA $File
if ($LASTEXITCODE) { throw 'release_signing_failed' }
