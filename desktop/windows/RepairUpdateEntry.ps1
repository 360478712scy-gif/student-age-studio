param(
    [string]$LocationsFile,
    [string]$UpdatesRoot
)

# Only move the known update-panel mount after its settings body is attached.
# Run after closing StudentAge Studio. Never change update state or user data.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function LineCount([string]$Text, [string]$Line) {
    return [regex]::Matches($Text, '(?m)^' + [regex]::Escape($Line) + '\r?$').Count
}

function HashBytes([byte[]]$Bytes) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function CheckPlainPath([string]$Path, [string]$Boundary) {
    $current = $Path
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Linked or redirected update paths are not supported; no file was changed.'
            }
        }
        if ($current.TrimEnd('\') -eq $Boundary.TrimEnd('\')) { break }
        $parent = [IO.Path]::GetDirectoryName($current)
        if ($parent -eq $current) { break }
        $current = $parent
    }
}

try {
    if (-not $LocationsFile) {
        if (-not $UpdatesRoot) {
            if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is unavailable.' }
            $UpdatesRoot = Join-Path $env:LOCALAPPDATA 'StudentAgeStudio\Updates'
        }
        if (-not [IO.Path]::IsPathRooted($UpdatesRoot)) { throw 'UpdatesRoot must be an absolute path.' }
        $UpdatesRoot = [IO.Path]::GetFullPath($UpdatesRoot)
        $stateFile = Join-Path $UpdatesRoot 'active.json'
        if (Test-Path -LiteralPath $stateFile -PathType Leaf) {
            CheckPlainPath $stateFile $UpdatesRoot
            $state = [IO.File]::ReadAllText($stateFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
            if ($state -isnot [pscustomobject]) { throw 'Unrecognized active.json; no file was changed.' }
            $activeProperty = $state.PSObject.Properties['active']
            $identifier = if ($null -eq $activeProperty) { $null } else { $activeProperty.Value }
            if ($null -ne $identifier -and $identifier -ne '') {
                if ($identifier -isnot [string] -or -not [regex]::IsMatch($identifier, '\A[A-Za-z0-9][A-Za-z0-9._-]{0,100}\z')) {
                    throw 'Unsafe active update identifier; no file was changed.'
                }
                $versions = [IO.Path]::GetFullPath((Join-Path $UpdatesRoot 'versions'))
                $candidate = [IO.Path]::GetFullPath((Join-Path $versions ($identifier + '\standalone\locations.js')))
                if (-not $candidate.StartsWith($versions.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
                    throw 'Update path escaped the versions folder; no file was changed.'
                }
                CheckPlainPath $candidate $UpdatesRoot
                if (Test-Path -LiteralPath $candidate -PathType Leaf) { $LocationsFile = $candidate }
            }
        }
        if (-not $LocationsFile) {
            Add-Type -AssemblyName System.Windows.Forms
            $picker = New-Object System.Windows.Forms.OpenFileDialog
            try {
                $picker.Title = 'Select the installed standalone\locations.js (close Studio first)'
                $picker.Filter = 'locations.js|locations.js'
                $picker.CheckFileExists = $true
                if ($picker.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) {
                    Write-Host 'Cancelled. No file was changed.'
                    exit 2
                }
                $LocationsFile = $picker.FileName
            } finally { $picker.Dispose() }
        }
    }
    if (-not [IO.Path]::IsPathRooted($LocationsFile)) { throw 'LocationsFile must be an absolute path.' }
    $LocationsFile = [IO.Path]::GetFullPath($LocationsFile)
    if ([IO.Path]::GetFileName($LocationsFile) -ine 'locations.js' -or -not (Test-Path -LiteralPath $LocationsFile -PathType Leaf)) {
        throw 'Select an existing file named locations.js; no file was changed.'
    }
    CheckPlainPath $LocationsFile ([IO.Path]::GetDirectoryName($LocationsFile))
    $original = [IO.File]::ReadAllBytes($LocationsFile)
    $encoding = New-Object Text.UTF8Encoding($false, $true)
    $text = $encoding.GetString($original)
    $beforeHash = HashBytes $original
    $oldMount = "    const update=document.createElement('section');update.className='location-section';update.dataset.settingsGroup='about';body.prepend(update);window.STUDIO_UPDATES?.mount(update);"
    $newMount = "    const update=document.createElement('section');update.className='location-section';update.dataset.settingsGroup='about';body.prepend(update);"
    $oldAppend = '    dialog.append(nav,body);selectTab();'
    $newAppend = '    dialog.append(nav,body);selectTab();window.STUDIO_UPDATES?.mount(update);'
    $mountCount = [regex]::Matches($text, [regex]::Escape('window.STUDIO_UPDATES?.mount(update);')).Count
    if ($mountCount -eq 1 -and (LineCount $text $newMount) -eq 1 -and (LineCount $text $newAppend) -eq 1) {
        Write-Host 'Already repaired. No file was changed.'
        @{status='already_fixed';target=$LocationsFile;beforeSha256=$beforeHash;afterSha256=$beforeHash} | ConvertTo-Json -Compress
        exit 0
    }
    if ($mountCount -ne 1 -or (LineCount $text $oldMount) -ne 1 -or (LineCount $text $oldAppend) -ne 1) {
        throw 'This file does not match the known update-entry issue. No file was changed.'
    }
    $patched = $text.Replace($oldMount, $newMount).Replace($oldAppend, $newAppend)
    $result = $encoding.GetBytes($patched)
    $afterHash = HashBytes $result
    $suffix = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N')
    $backup = $LocationsFile + '.update-entry-' + $suffix + '.bak'
    $temporary = $LocationsFile + '.update-entry-' + $suffix + '.tmp'
    [IO.File]::WriteAllBytes($backup, $original)
    if ((HashBytes ([IO.File]::ReadAllBytes($backup))) -ne $beforeHash) { throw 'Backup verification failed; repair stopped.' }
    [IO.File]::WriteAllBytes($temporary, $result)
    if ((HashBytes ([IO.File]::ReadAllBytes($LocationsFile))) -ne $beforeHash) { throw 'The file changed during repair; repair stopped. The backup was kept.' }
    [IO.File]::Replace($temporary, $LocationsFile, $backup)
    if ((HashBytes ([IO.File]::ReadAllBytes($backup))) -ne $beforeHash) { throw 'Final backup verification failed. The backup was kept.' }
    if ((HashBytes ([IO.File]::ReadAllBytes($LocationsFile))) -ne $afterHash) { throw 'Repaired file verification failed. The backup was kept.' }
    Write-Host ('Update entry repaired. Backup: ' + $backup)
    Write-Host 'Reopen Studio, then Workshop settings > Version and feedback.'
    @{status='fixed';target=$LocationsFile;backup=$backup;beforeSha256=$beforeHash;afterSha256=$afterHash} | ConvertTo-Json -Compress
    exit 0
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
