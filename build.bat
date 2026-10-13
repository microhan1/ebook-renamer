@echo off
rem Build ebook-renamer.exe (single file, no console) with PyInstaller.
rem Usage: build.bat          -> dist\ebook-renamer.exe
setlocal
cd /d "%~dp0"

python -m PyInstaller --version >nul 2>&1 || python -m pip install pyinstaller
python -m pip install -r requirements.txt

python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name ebook-renamer ^
  --icon assets\icon.ico ^
  --add-data "lang;lang" ^
  --collect-data tkinterdnd2 ^
  --exclude-module numpy --exclude-module PIL --exclude-module pillow_heif --exclude-module lxml ^
  main.py

if errorlevel 1 (
  echo Build failed.
  exit /b 1
)
echo.
echo Done: dist\ebook-renamer.exe
endlocal
