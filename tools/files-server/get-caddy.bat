@echo off
setlocal
cd /d "%~dp0"

rem Fetches the pinned Caddy release into this folder as caddy.exe and checks
rem its SHA-512 against the value published with that release. Nothing else:
rem no installer, no registry, no service. Re-run to replace it.
rem To move to a newer Caddy, update VERSION and SHA512 together - the hash is
rem in caddy_<version>_checksums.txt on the GitHub release page.

set "VERSION=2.11.4"
set "SHA512=cd5ccfd86a4b40732cf715890d0dca5bf3f63adefec5a7914de85adf240c60ce7e5d2791631b88ef9758e46b23bb1730e020b9c5d696889740b284ffd4788e35"
set "ZIP=caddy_%VERSION%_windows_amd64.zip"
set "URL=https://github.com/caddyserver/caddy/releases/download/v%VERSION%/%ZIP%"

echo Downloading Caddy %VERSION% ...
curl.exe -fL --progress-bar -o "%ZIP%" "%URL%"
if errorlevel 1 (
    echo Download failed.
    del "%ZIP%" 2>nul
    exit /b 1
)

echo Verifying checksum ...
set "GOT="
for /f "skip=1 tokens=* delims=" %%H in ('certutil -hashfile "%ZIP%" SHA512 ^| findstr /v /i "certutil"') do (
    if not defined GOT set "GOT=%%H"
)
set "GOT=%GOT: =%"
if /i not "%GOT%"=="%SHA512%" (
    echo Checksum mismatch - not using this download.
    echo   expected %SHA512%
    echo   got      %GOT%
    del "%ZIP%" 2>nul
    exit /b 1
)

echo Unpacking ...
tar.exe -xf "%ZIP%" caddy.exe
if errorlevel 1 (
    echo Could not unpack %ZIP%.
    exit /b 1
)
del "%ZIP%" 2>nul

.\caddy.exe version
echo.
echo caddy.exe is ready. Start the server with serve.bat.
