$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new()
$source=if($env:STUDIO_SOURCE_ROOT){$env:STUDIO_SOURCE_ROOT}else{(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path}
$root=if($env:STUDIO_BUILD_ROOT){$env:STUDIO_BUILD_ROOT}else{Join-Path $env:LOCALAPPDATA 'StudentAgeStudioBuild'}
$python=Join-Path $root 'venv\Scripts\python.exe'
if(-not $env:STUDIO_REUSE_BUILD_DEPS){
 & $python -m pip install --disable-pip-version-check imageio-ffmpeg numpy
 if($LASTEXITCODE -ne 0){throw 'ffmpeg failed'}
}
$stage=Join-Path $root 'source'
# Recreate staged data so deleted source files cannot leak into later packages.
if(Test-Path "$stage\standalone"){Remove-Item "$stage\standalone" -Recurse -Force}
New-Item -ItemType Directory -Force "$stage\standalone" | Out-Null
Get-ChildItem "$source\standalone" -File | Where-Object {$_.Extension -in '.py','.js','.json','.html','.css','.png','.svg'} | Copy-Item -Destination "$stage\standalone" -Force
if(Test-Path "$stage\standalone\ui-assets"){Remove-Item "$stage\standalone\ui-assets" -Recurse -Force}
Copy-Item "$source\standalone\ui-assets" "$stage\standalone\ui-assets" -Recurse -Force
Copy-Item "$source\desktop\windows\main.py" "$stage\main.py" -Force
Copy-Item "$source\desktop\windows\child_processes.py" "$stage\child_processes.py" -Force
Set-Location $stage
$out=Join-Path $root 'dist'
$cleanArgs=@();if(-not $env:STUDIO_INCREMENTAL_BUILD){$cleanArgs=@('--clean')}
& $python -m PyInstaller --noconfirm @cleanArgs --name StudioEngine --console --icon "$source\desktop\windows\studio.ico" --distpath $out --workpath "$root\work" --specpath $root --paths "$stage\standalone" --add-data "$stage\standalone;standalone" --collect-all webview --collect-all UnityPy --collect-data archspec --collect-all imageio_ffmpeg --hidden-import server --hidden-import platform_support --hidden-import game_locator --hidden-import PIL.Image --hidden-import numpy --exclude-module PyQt5 --exclude-module PySide6 "$stage\main.py"
if($LASTEXITCODE -ne 0){throw 'Freezing failed'}
$version=& $python -c "import sys;sys.path.insert(0,sys.argv[1]);from error_logs import APP_VERSION;print(APP_VERSION)" "$stage\standalone"
if($LASTEXITCODE -ne 0){throw 'Version read failed'}
$packageName=if($env:STUDIO_PACKAGE_NAME){$env:STUDIO_PACKAGE_NAME}else{'StudentAgeStudio-Windows-'+$version.Trim()}
$package=Join-Path $root $packageName
New-Item -ItemType Directory -Force $package | Out-Null
if(Test-Path "$package\runtime"){Remove-Item "$package\runtime" -Recurse -Force}
Move-Item "$out\StudioEngine" "$package\runtime"
New-Item -ItemType Directory -Force "$package\runtime\_internal\archspec\cpu" | Out-Null
$audioLib="$root\venv\Lib\site-packages\fmod_toolkit\libfmod\Windows\x64"
New-Item -ItemType Directory -Force "$package\runtime\_internal\fmod_toolkit\libfmod\Windows" | Out-Null
Copy-Item $audioLib "$package\runtime\_internal\fmod_toolkit\libfmod\Windows\x64" -Recurse -Force
$csc=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $csc /nologo /target:winexe "/win32icon:$source\desktop\windows\studio.ico" /reference:System.Windows.Forms.dll "/out:$package\拾光工坊.exe" "$source\desktop\windows\Launcher.cs"
if($LASTEXITCODE -ne 0){throw 'Launcher failed'}
& $python -m pip freeze | Out-File "$package\dependencies.txt" -Encoding utf8
Copy-Item "$source\desktop\windows\使用说明.txt" $package -Force
Copy-Item "$source\LICENSE" $package -Force
Copy-Item "$source\THIRD_PARTY_NOTICES.md" $package -Force
Write-Output ('PACKAGE='+$package)
