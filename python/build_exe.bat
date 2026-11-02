@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Сборка AtributyAGR_Trainer.exe (5-10 минут, нужен интернет) ===

rem Ищем Python: сначала запускатель py (он не перехватывается Microsoft Store), потом python
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (
  python -c "import sys" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Не найден Python. Установите Python 3.12 с python.org, отметьте "Add to PATH".
  pause & exit /b 1
)
echo Python: %PY%
%PY% --version

if not exist .venv (
  %PY% -m venv .venv || goto err
)
call .venv\Scripts\activate.bat || goto err
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller || goto err

python -m PyInstaller --noconfirm --onedir --windowed --name AtributyAGR_Trainer --collect-all ifcopenshell app.py || goto err

echo.
echo Готово: dist\AtributyAGR_Trainer\AtributyAGR_Trainer.exe
echo Папку dist\AtributyAGR_Trainer можно целиком скопировать на любой компьютер с Windows.
explorer dist\AtributyAGR_Trainer
pause
exit /b 0

:err
echo.
echo Ошибка сборки - пришлите текст выше.
pause
exit /b 1
