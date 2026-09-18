@echo off
setlocal

:: rattler-build downloads, verifies and extracts the pinned release archive, so
:: BACKEND, FORK and VERSION (build.script.env) are only used for logging here.
:: Linux is handled by build.sh.
::
:: Executables and DLLs are installed together into %PREFIX%\bin: that
:: directory is on PATH in an activated pixi environment, executables find their
:: DLLs in their own directory, and dynamic backend loading (GGML_BACKEND_DL)
:: scans the executable's directory for ggml-*.dll. Windows zips are flat, but
:: the recursive copy does not depend on that.
echo Installing the %BACKEND% build of %FORK% %VERSION% into %PREFIX%

:: The build prefix is reused between builds, so clear the directory this recipe
:: owns: last time's DLLs must not be packaged alongside this time's.
if exist "%PREFIX%\bin" rmdir /s /q "%PREFIX%\bin"
if not exist "%PREFIX%\bin" mkdir "%PREFIX%\bin"
for /r . %%f in (*.exe) do copy /y "%%f" "%PREFIX%\bin" >nul || exit /b 1
for /r . %%f in (*.dll) do copy /y "%%f" "%PREFIX%\bin" >nul || exit /b 1
if not exist "%PREFIX%\bin\llama-server.exe" (
    echo llama-server.exe is missing from the extracted release asset
    exit /b 1
)

:: The Windows release archives ship no LICENSE file, and the recipe's
:: `about.license_file` needs one. FORK is `owner/repo`, so the raw host needs
:: the same path. Retry: the raw host is occasionally unavailable.
curl -sL --retry 5 --retry-delay 5 --retry-all-errors --fail "https://raw.githubusercontent.com/%FORK%/%VERSION%/LICENSE" -o LICENSE || exit /b 1
