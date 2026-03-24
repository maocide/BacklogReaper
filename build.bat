@echo off
echo Building Backlog Reaper...

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Test imports before wasting time on a build
echo.
echo Verifying dependencies...
python -c "import thefuzz; import basc_py4chan; import ddgs; import bs4; import howlongtobeatpy; import networkx; import sympy; import openai; import requests; import steam_web_api; import steamspypi; import flet; import flet_charts; import PIL; import trafilatura; import sentence_transformers; import numpy; import kagglehub; import tiktoken; import lxml_html_clean; import cryptography; print('All imports successful!')"

REM Check if Python crashed
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Import test failed! You are missing dependencies.
    echo Please run 'pip install -r requirements.txt' again.
    echo Aborting build.
    goto end
)

REM Clean previous build directories
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

REM Build executable
echo.
echo Running flet pack...
flet pack main.py --onedir --name "Backlog Reaper" --icon assets\reaper_icon.ico --add-data "assets;assets" --pyinstaller-build-args="--copy-metadata=tiktoken" --pyinstaller-build-args="--collect-data=tiktoken" --pyinstaller-build-args="--hidden-import=tiktoken_ext" --pyinstaller-build-args="--hidden-import=tiktoken_ext.openai_public" --pyinstaller-build-args="--collect-data=sentence_transformers" --pyinstaller-build-args="--collect-data=transformers" --pyinstaller-build-args="--copy-metadata=python-steam-api"

REM Check if the executable was actually created
if exist "dist\Backlog Reaper\Backlog Reaper.exe" (
    echo.
    echo Build successful: dist\Backlog Reaper\Backlog Reaper.exe
    dir "dist\Backlog Reaper\"
) else (
    echo.
    echo Build failed!
)

:end
pause