@echo off
chcp 65001 > nul 2>&1

echo ==========================================
echo   Notion Files Management - Self Contained
echo   Includes .NET 8 Runtime
echo ==========================================

set PROJECT_NAME=Notion-Files-Management
set CONFIG=Release
set RID=win-x64
set OUTPUT_DIR=bin\%CONFIG%\net8.0-windows\%RID%\publish

echo.
echo Cleaning old publish directory...
if exist "%OUTPUT_DIR%" (
    rmdir /s /q "%OUTPUT_DIR%" 2>nul
)

echo.
echo Publishing for %RID%...
echo.

:: Check if icon file exists
if not exist "icon.ico" (
    echo ERROR: icon.ico not found in project root directory!
    echo Please place icon.ico file in the project root.
    pause
    exit /b 1
)

echo Using icon.ico for application icon...

:: Publish command
dotnet publish -c %CONFIG% -r %RID% ^
    --self-contained true ^
    /p:PublishSingleFile=true ^
    /p:IncludeAllContentForSelfExtract=true ^
    /p:ExcludeSingleFileDependencies=false ^
    /p:IncludeNativeLibrariesForSelfExtract=true ^
    /p:DebugType=None ^
    /p:DebugSymbols=false ^
    /p:CopyOutputSymbolsToPublishDirectory=false ^
    /p:PublishReadyToRun=true ^
    /p:PublishTrimmed=true ^
    /p:TrimMode=partial ^
    /p:EnableCompressionInSingleFile=true ^
    /p:ApplicationIcon=icon.ico

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Build failed!
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ==========================================
echo [SUCCESS] Build completed!
echo Output directory: %OUTPUT_DIR%
echo ==========================================

echo.
echo Files in publish directory:
dir "%OUTPUT_DIR%" /b

echo.
echo Main executable: %OUTPUT_DIR%\%PROJECT_NAME%.exe

:: Get file size
for %%F in ("%OUTPUT_DIR%\%PROJECT_NAME%.exe") do (
    set /a size=%%~zF
)
set /a sizeMB=size/1048576
echo File size: %sizeMB% MB
echo.

echo Note: This version includes .NET 8 Runtime.
echo Can run on any Windows PC without installing .NET 8.
echo.

pause