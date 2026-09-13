@echo off
setlocal
cd /d "%~dp0"

rem cn4m files server - serves the workspace over HTTP for the "open in player"
rem menu. Runs in this window until Ctrl+C; nothing is installed or registered.
rem Fetch caddy.exe first with get-caddy.bat.

if not exist caddy.exe (
    echo caddy.exe not found. Run get-caddy.bat first.
    exit /b 1
)

rem Serve the same folder cn4m works on: WORKSPACE_FOLDER from the repo's .env,
rem unless CN4M_FILES_ROOT is already set in this shell to point somewhere else.
if not defined CN4M_FILES_ROOT (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("..\..\.env") do (
        if /i "%%A"=="WORKSPACE_FOLDER" set "CN4M_FILES_ROOT=%%B"
    )
)
if not defined CN4M_FILES_ROOT (
    echo WORKSPACE_FOLDER is not set in ..\..\.env and CN4M_FILES_ROOT is not set.
    exit /b 1
)
set "CN4M_FILES_ROOT=%CN4M_FILES_ROOT:"=%"
set "CN4M_FILES_ROOT=%CN4M_FILES_ROOT:'=%"
if not exist "%CN4M_FILES_ROOT%\" (
    echo Workspace folder not found: %CN4M_FILES_ROOT%
    exit /b 1
)

if not defined CN4M_FILES_PORT set "CN4M_FILES_PORT=2648"

echo.
echo   cn4m files server
echo   serving  %CN4M_FILES_ROOT%
echo   on       http://0.0.0.0:%CN4M_FILES_PORT%/   (read-only)
echo   Ctrl+C to stop.
echo.
.\caddy.exe run --config Caddyfile --adapter caddyfile
