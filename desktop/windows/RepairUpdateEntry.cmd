@echo off
setlocal
echo Close StudentAge Studio before running this repair.
echo This repair only restores the update panel entry.
pause
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0RepairUpdateEntry.ps1" %*
set "RepairExitCode=%ERRORLEVEL%"
echo.
if "%RepairExitCode%"=="0" echo Done. Reopen Studio and check Version and feedback in Workshop settings.
pause
exit /b %RepairExitCode%
