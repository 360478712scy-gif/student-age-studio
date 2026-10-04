param([Parameter(Mandatory=$true)][string]$Package)
$ErrorActionPreference='Stop'
$root=(Resolve-Path $Package).Path
$launcher=Get-ChildItem -LiteralPath $root -Filter *.exe | Select-Object -First 1
$dll=Join-Path $root 'runtime\_internal\pythonnet\runtime\Python.Runtime.dll'
if(!$launcher -or !(Test-Path -LiteralPath $dll)){throw 'Packaged launcher or Python.Runtime.dll missing'}
$assembly=[Reflection.Assembly]::LoadFile($launcher.FullName)
$type=$assembly.GetType('Launcher')
$flags=[Reflection.BindingFlags]'NonPublic,Static'
$inspect=$type.GetMethod('InspectRuntime',$flags)
$prepare=$type.GetMethod('PrepareRuntime',$flags)
if(!$inspect -or !$prepare){throw 'Failure-only runtime diagnostics missing'}
function Inspect-Code {
 $result=$inspect.Invoke($null,@($root))
 return $result.GetType().GetField('Code').GetValue($result)
}
$original=[IO.File]::ReadAllBytes($dll)
$originalMark=Get-Content -LiteralPath $dll -Stream Zone.Identifier -ErrorAction SilentlyContinue
try {
 Set-Content -LiteralPath $dll -Stream Zone.Identifier -Value ("[ZoneTransfer]"+[Environment]::NewLine+"ZoneId=3")
 if((Inspect-Code) -ne 'package_ok'){throw 'Valid marked package was rejected'}
 if(!(Get-Item -LiteralPath $dll -Stream Zone.Identifier -ErrorAction SilentlyContinue)){throw 'Read-only diagnosis changed a download mark'}
 $prepare.Invoke($null,@($root))
 if(Get-Item -LiteralPath $dll -Stream Zone.Identifier -ErrorAction SilentlyContinue){throw 'Explicit repair did not remove download mark'}
 $changed=[byte[]]($original + 1)
 [IO.File]::WriteAllBytes($dll,$changed)
 Set-Content -LiteralPath $dll -Stream Zone.Identifier -Value ("[ZoneTransfer]"+[Environment]::NewLine+"ZoneId=3")
 if((Inspect-Code) -ne 'package_changed'){throw 'Changed runtime was not classified'}
 $refused=$false
 try {$prepare.Invoke($null,@($root))} catch {$refused=$true}
 if(!$refused -or !(Get-Item -LiteralPath $dll -Stream Zone.Identifier -ErrorAction SilentlyContinue)){throw 'Repair modified an unverified DLL'}
 [IO.File]::WriteAllBytes($dll,$original)
 Remove-Item -LiteralPath $dll
 if((Inspect-Code) -ne 'package_missing'){throw 'Missing runtime was not classified'}
} finally {
 [IO.File]::WriteAllBytes($dll,$original)
 if($originalMark){Set-Content -LiteralPath $dll -Stream Zone.Identifier -Value $originalMark}
 else{Unblock-File -LiteralPath $dll}
}
$runtime=[Reflection.Assembly]::LoadFile($dll)
if(!$runtime.GetType('Python.Runtime.Loader').GetMethod('Initialize')){throw 'Python runtime entry point unavailable'}
$probe=Join-Path $root 'runtime-diagnostics.json'
& (Join-Path $root 'runtime\StudioEngine.exe') --diagnose-runtime --diagnostic-json $probe
if($LASTEXITCODE -ne 0){throw "Frozen runtime diagnostics failed: $LASTEXITCODE"}
$report=Get-Content -LiteralPath $probe -Raw | ConvertFrom-Json
if($report.code -ne 'ok' -or !$report.readOnly){throw 'Frozen runtime diagnostic report was not successful/read-only'}
'WINDOWS_LAUNCHER_RUNTIME_OK'
