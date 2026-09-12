param([Parameter(Mandatory=$true)][string]$Package)
$ErrorActionPreference='Stop'
$root=(Resolve-Path $Package).Path
$launcher=Get-ChildItem -LiteralPath $root -Filter *.exe | Select-Object -First 1
$dll=Join-Path $root 'runtime\_internal\pythonnet\runtime\Python.Runtime.dll'
if(!$launcher -or !(Test-Path -LiteralPath $dll)){throw 'Packaged launcher or Python.Runtime.dll missing'}
$assembly=[Reflection.Assembly]::LoadFile($launcher.FullName)
$prepare=$assembly.GetType('Launcher').GetMethod('PrepareRuntime',[Reflection.BindingFlags]'NonPublic,Static')
if(!$prepare){throw 'Verified runtime preparation missing'}
try {
 Set-Content -LiteralPath $dll -Stream Zone.Identifier -Value "[ZoneTransfer]`r`nZoneId=3"
 $prepare.Invoke($null,@($root))
 if(Get-Item -LiteralPath $dll -Stream Zone.Identifier -ErrorAction SilentlyContinue){throw 'Downloaded runtime remains blocked'}
 $runtime=[Reflection.Assembly]::LoadFile($dll)
 if(!$runtime.GetType('Python.Runtime.Loader').GetMethod('Initialize')){throw 'Python runtime entry point unavailable'}
 'WINDOWS_LAUNCHER_RUNTIME_OK'
} finally {Unblock-File -LiteralPath $dll}
