[CmdletBinding()]
param(
    [string]$OutputRoot = (Join-Path $PSScriptRoot 'artifacts'),
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot '..'),
    [switch]$AllowAgentNetwork
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$outputFull = [System.IO.Path]::GetFullPath($OutputRoot)
$artifactDir = [System.IO.Path]::GetFullPath((Join-Path $outputFull 'formfiller-clean-source'))

if (-not $artifactDir.StartsWith($outputFull.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'The clean source destination must be inside the selected artifact directory.'
}
if (Test-Path -LiteralPath $artifactDir) {
    $resolvedArtifact = (Resolve-Path -LiteralPath $artifactDir).Path
    if ($resolvedArtifact -ne $artifactDir) { throw 'Refusing to replace a reparse-point artifact directory.' }
    Remove-Item -LiteralPath $artifactDir -Recurse -Force
}
New-Item -ItemType Directory -Path (Join-Path $artifactDir 'formfiller') -Force | Out-Null

# Keep this allowlist explicit. Never copy outputs/config, outputs/state, reports,
# browser data, user workspaces, or arbitrary files discovered in the checkout.
$sourceNames = @(
    '__init__.py',
    'browser.py',
    'calendar.py',
    'calendar_xlsx.py',
    'default_calendar.py',
    'deployment.py',
    'migrate.py',
    'monitor.py',
    'ownership.py',
    'run_and_check.py',
    'runner.py',
    'scheduling.py',
    'taskplan.py',
    'schema_changes.py',
    'skyward.py',
    'state.py',
    'store.py',
    'workspace.py',
    'web.py'
)
foreach ($name in $sourceNames) {
    $source = Join-Path $repoRoot (Join-Path 'outputs\formfiller' $name)
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Required source file is missing: outputs/formfiller/$name" }
    Copy-Item -LiteralPath $source -Destination (Join-Path $artifactDir (Join-Path 'formfiller' $name))
}
$assetRoot = Join-Path $repoRoot 'outputs\formfiller\web_static'
if (Test-Path -LiteralPath $assetRoot -PathType Container) {
    if (((Get-Item -LiteralPath $assetRoot -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Refusing a linked web asset root.' }
    $assetExtensions = @('.html', '.js', '.css', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.ico', '.woff', '.woff2')
    foreach ($asset in Get-ChildItem -LiteralPath $assetRoot -Force -Recurse) {
        if (($asset.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Refusing a linked web asset.' }
        if ($asset.PSIsContainer) { continue }
        if ($asset.Extension.ToLowerInvariant() -in @('.py', '.pyc')) { continue }
        if ($assetExtensions -notcontains $asset.Extension.ToLowerInvariant()) { throw "Unsupported web asset type: $($asset.Extension)" }
        $relativeAsset = [System.IO.Path]::GetRelativePath($assetRoot, $asset.FullName)
        $targetAsset = Join-Path (Join-Path $artifactDir 'formfiller\web_static') $relativeAsset
        New-Item -ItemType Directory -Path (Split-Path -Parent $targetAsset) -Force | Out-Null
        Copy-Item -LiteralPath $asset.FullName -Destination $targetAsset
    }
}
$requirements = Join-Path $repoRoot 'outputs\requirements.txt'
if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) { throw 'outputs/requirements.txt is missing.' }
Copy-Item -LiteralPath $requirements -Destination (Join-Path $artifactDir 'requirements.txt')
@'
Clean source bundle

This directory contains only explicitly allowlisted application source, static
web assets, and the dependency manifest. It has no user configuration,
responses, browser profile, calendar snapshot, reports, or persistent run state.

For isolated development, open the generated FormFiller-Development.wsb and
copy this directory inside Windows Sandbox before editing. Networking is off.
'@ | Set-Content -LiteralPath (Join-Path $artifactDir 'README.txt') -Encoding UTF8

$wsbPath = Join-Path $outputFull 'FormFiller-Development.wsb'
$escapedHost = [System.Security.SecurityElement]::Escape($artifactDir)
$networkMode = if ($AllowAgentNetwork) { 'Enable' } else { 'Disable' }
$wsb = @"
<Configuration>
  <Networking>$networkMode</Networking>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>$escapedHost</HostFolder>
      <SandboxFolder>C:\FormFillerSource</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <PrinterRedirection>Disable</PrinterRedirection>
  <AudioInput>Disable</AudioInput>
  <VideoInput>Disable</VideoInput>
  <ProtectedClient>Enable</ProtectedClient>
  <MemoryInMB>4096</MemoryInMB>
</Configuration>
"@
Set-Content -LiteralPath $wsbPath -Value $wsb -Encoding UTF8
Write-Output "Clean source: $artifactDir"
Write-Output "Sandbox file: $wsbPath"
if ($AllowAgentNetwork) {
    Write-Output 'Sandbox networking is enabled by explicit request; only the clean source bundle is mounted.'
} else {
    Write-Output 'Sandbox networking is disabled.'
}
Write-Output 'The host checkout remains accessible to local tools; this only defines the Windows Sandbox boundary.'
