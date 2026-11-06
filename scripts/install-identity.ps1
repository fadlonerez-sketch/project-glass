<#
  Give Project Glass package identity (sparse MSIX with an external location), so it may mirror Windows
  notifications. See docs\NOTIFICATIONS.md.

  Run from the ProjectGlass folder:
      powershell -ExecutionPolicy Bypass -File scripts\install-identity.ps1
  Remove:
      Get-AppxPackage ProjectGlass.Identity | Remove-AppxPackage
      Get-ChildItem Cert:\CurrentUser\TrustedPeople, Cert:\CurrentUser\My |
          Where-Object Subject -eq 'CN=Project Glass Local' | Remove-Item

  STATUS: written to Microsoft's documented procedure ("Grant package identity by packaging with external
  location manually", learn.microsoft.com) but NOT yet run on this PC.

  Supply chain: makeappx/signtool come from the Microsoft.Windows.SDK.BuildTools NuGet package. The download is
  refused unless its SHA-512 matches $PinnedSha512 below (nuget.org's published "Package hash" for that exact
  version), and both tools must carry a valid Microsoft Authenticode signature. To use another version, change
  $BuildToolsVersion and pass -BuildToolsSha512 '<Package hash from nuget.org>' (base64 or hex) or
  -BuildToolsSha256 <hex>; take the hash from nuget.org, never from the file you just downloaded.

  Signing key: the self-signed certificate is created with a NON-EXPORTABLE private key in CurrentUser\My and
  signtool signs from the store by thumbprint, so no PFX file or password ever exists.

  Trust: per Microsoft's sparse-package guidance, a per-user Add-AppxPackage accepts a self-signed package
  whose public certificate is in Cert:\CurrentUser\TrustedPeople, so no administrator approval is needed and
  nothing is trusted machine-wide. If registration still fails with 0x800B0109 (CERT_E_UNTRUSTEDROOT), rerun
  with -MachineWideTrust to import it into LocalMachine\TrustedPeople instead (one elevation prompt).
#>
param(
    [string]$BuildToolsSha256 = '',
    [string]$BuildToolsSha512 = '',
    [switch]$MachineWideTrust
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$work = Join-Path $env:LOCALAPPDATA 'ProjectGlass\identity'
New-Item -ItemType Directory -Force -Path $work | Out-Null
$subject = 'CN=Project Glass Local'

$BuildToolsVersion = '10.0.28000.2957'
# nuget.org packageHash (SHA-512, base64) for exactly $BuildToolsVersion, from the catalog entry
# api.nuget.org/v3/catalog0/data/2026.10.28.18.05.16/microsoft.windows.sdk.buildtools.10.0.28000.2957.json
# and cross-checked against an independently downloaded copy (22,369,897 bytes; SHA-256
# B7163FC6F636172726D0985963E4F7F11C41AFE1C7FDFE78F8051877360ED696). Change both lines together.
$PinnedSha512 = 'PhfL6f1d9c2CXCD2fyQkwBBFR6/csgVxWDWDj/9uIY3PU5aUR3vtoAJn7HP1d/cMrHGQhuSH1FXHvaZIjOIajw=='

# Returns @{ Algorithm = 'SHA256'|'SHA512'; Hex = <upper-case hex> }. An explicit -BuildToolsSha256 or
# -BuildToolsSha512 wins over the pin; SHA-512 may be base64 (as nuget.org shows it) or 128 hex characters.
function Get-ExpectedHash([string]$Sha256, [string]$Sha512, [string]$Pinned512) {
    $Sha256 = "$Sha256".Trim()
    if ($Sha256) {
        if ($Sha256 -notmatch '^[0-9A-Fa-f]{64}$') { throw 'BuildToolsSha256 must be 64 hex characters.' }
        return @{ Algorithm = 'SHA256'; Hex = $Sha256.ToUpperInvariant() }
    }
    $s = ($Sha512, $Pinned512 | ForEach-Object { "$_".Trim() } | Where-Object { $_ } | Select-Object -First 1)
    if ($s) {
        if ($s -match '^[0-9A-Fa-f]{128}$') { return @{ Algorithm = 'SHA512'; Hex = $s.ToUpperInvariant() } }
        try { $bytes = [Convert]::FromBase64String($s) } catch { throw 'BuildToolsSha512 must be base64 (as nuget.org shows it) or 128 hex characters.' }
        if ($bytes.Length -ne 64) { throw 'BuildToolsSha512 does not decode to a 64-byte SHA-512 hash.' }
        return @{ Algorithm = 'SHA512'; Hex = (($bytes | ForEach-Object { $_.ToString('X2') }) -join '') }
    }
    throw ("Refusing to download build tools without an expected hash. Look up Microsoft.Windows.SDK.BuildTools " +
           "$BuildToolsVersion on nuget.org and pass -BuildToolsSha512 '<Package hash>' (or -BuildToolsSha256 <hex>).")
}

# True only when the file's hash equals the expected one (from Get-ExpectedHash).
function Test-ExpectedHash([string]$Path, [hashtable]$Expected) {
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm $Expected.Algorithm).Hash.ToUpperInvariant()
    return [string]::Equals($actual, $Expected.Hex, [System.StringComparison]::Ordinal)
}

# Valid Authenticode signature whose signer AND issuing CA both have exactly O=Microsoft Corporation
# (a whole RDN, so e.g. "O=Microsoft Corporation Fake Ltd" does not pass).
function Assert-MicrosoftSigned([System.IO.FileInfo]$file) {
    if (-not $file) { throw 'A required build tool was not found in the package.' }
    $sig = Get-AuthenticodeSignature -LiteralPath $file.FullName
    $msOrg = '(^|,\s*)O=Microsoft Corporation(\s*,|$)'
    if ($sig.Status -ne 'Valid' -or -not $sig.SignerCertificate -or
        $sig.SignerCertificate.Subject -notmatch $msOrg -or $sig.SignerCertificate.Issuer -notmatch $msOrg) {
        throw "$($file.Name) is not validly signed by Microsoft (status: $($sig.Status)). Not using it."
    }
}

Write-Host '1/4  Windows SDK build tools (makeappx, signtool)'
$expected = Get-ExpectedHash $BuildToolsSha256 $BuildToolsSha512 $PinnedSha512
$tools = Join-Path $work 'buildtools'
$marker = Join-Path $tools 'verified-hash.txt'
$verified = (Test-Path $marker) -and ((Get-Content $marker -Raw).Trim() -eq "$($expected.Algorithm):$($expected.Hex)")
if (-not $verified) {
    Remove-Item -Recurse -Force $tools -ErrorAction SilentlyContinue
    $nupkg = Join-Path $work 'buildtools.zip'
    Invoke-WebRequest "https://www.nuget.org/api/v2/package/Microsoft.Windows.SDK.BuildTools/$BuildToolsVersion" -OutFile $nupkg -UseBasicParsing
    if (-not (Test-ExpectedHash $nupkg $expected)) {
        $actual = (Get-FileHash -LiteralPath $nupkg -Algorithm $expected.Algorithm).Hash
        Remove-Item -Force -LiteralPath $nupkg
        throw "Build tools hash mismatch ($($expected.Algorithm)): expected $($expected.Hex), got $actual. Download discarded."
    }
    Expand-Archive $nupkg -DestinationPath $tools -Force
    Remove-Item -Force $nupkg
    Set-Content -Path $marker -Value "$($expected.Algorithm):$($expected.Hex)" -Encoding ASCII
}
$makeappx = Get-ChildItem $tools -Recurse -Filter makeappx.exe | Where-Object FullName -match '\\x64\\' | Select-Object -First 1
$signtool = Get-ChildItem $tools -Recurse -Filter signtool.exe | Where-Object FullName -match '\\x64\\' | Select-Object -First 1
Assert-MicrosoftSigned $makeappx
Assert-MicrosoftSigned $signtool

Write-Host '2/4  Package layout and logos'
$layout = Join-Path $work 'layout'
Remove-Item -Recurse -Force $layout -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path (Join-Path $layout 'assets') | Out-Null
Copy-Item (Join-Path $root 'packaging\AppxManifest.xml') $layout
# Paths go in as arguments (not spliced into the code), so no path can break or change the Python source.
$logoScript = @'
import os, sys
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtCore import Qt
app = QGuiApplication(sys.argv[:1])
src = QImage(sys.argv[1])
for px, name in ((150, 'glass150.png'), (44, 'glass44.png')):
    src.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation).save(os.path.join(sys.argv[2], name))
'@
& (Join-Path $root '.venv\Scripts\python.exe') -c $logoScript (Join-Path $root 'assets\glass.ico') (Join-Path $layout 'assets')
if ($LASTEXITCODE -ne 0) { throw 'Rendering the package logos failed.' }
$msix = Join-Path $work 'ProjectGlass.Identity.msix'
& $makeappx.FullName pack /d $layout /p $msix /nv /o
if ($LASTEXITCODE -ne 0) { throw 'makeappx failed.' }

Write-Host '3/4  Signing (self-signed certificate, non-exportable key, trusted for this user only)'
$cert = Get-ChildItem Cert:\CurrentUser\My |
    Where-Object { $_.Subject -eq $subject -and $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date).AddDays(1) } |
    Sort-Object NotAfter -Descending | Select-Object -First 1
if (-not $cert) {
    $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $subject -CertStoreLocation Cert:\CurrentUser\My `
        -KeyExportPolicy NonExportable -KeyUsage DigitalSignature -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 `
        -NotAfter (Get-Date).AddYears(2) -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3', '2.5.29.19={text}')
}
# Sign from CurrentUser\My by thumbprint: the private key never leaves the store.
& $signtool.FullName sign /fd SHA256 /sha1 $cert.Thumbprint /s My $msix
if ($LASTEXITCODE -ne 0) { throw 'signtool failed.' }
$cer = Join-Path $work 'identity.cer'
Export-Certificate -Cert $cert -FilePath $cer | Out-Null      # public part only
if ($MachineWideTrust) {
    Write-Host '     Windows will ask for administrator approval to trust this certificate (LocalMachine\TrustedPeople).'
    # The elevated process gets the public certificate inline (base64 data, not a path in a user-writable
    # folder that could be swapped before it runs) and re-checks the thumbprint before trusting it. The whole
    # command travels as -EncodedCommand, so nothing in it is re-parsed by the command line.
    $certB64 = [Convert]::ToBase64String($cert.RawData)
    $elevated = @"
`$ErrorActionPreference = 'Stop'
`$c = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(,[Convert]::FromBase64String('$certB64'))
if (`$c.Thumbprint -ne '$($cert.Thumbprint)') { exit 2 }
`$store = New-Object System.Security.Cryptography.X509Certificates.X509Store('TrustedPeople', 'LocalMachine')
`$store.Open('ReadWrite')
try { `$store.Add(`$c) } finally { `$store.Close() }
"@
    $encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($elevated))
    $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $p = Start-Process $ps -Verb RunAs -Wait -PassThru -ArgumentList "-NoProfile -NonInteractive -EncodedCommand $encoded"
    if ($p.ExitCode -ne 0) { throw "Trusting the certificate machine-wide failed (exit code $($p.ExitCode))." }
} else {
    Import-Certificate -FilePath $cer -CertStoreLocation Cert:\CurrentUser\TrustedPeople | Out-Null
}

Write-Host '4/4  Registering the sparse package'
Add-AppxPackage -Path $msix -ExternalLocation $root
Write-Host ''
Write-Host 'Done. Start "Project Glass (with notifications)" from the Start menu instead of "Project Glass",'
Write-Host 'then allow notification access when Windows asks.'
