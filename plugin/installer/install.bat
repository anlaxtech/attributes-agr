@echo off
chcp 65001 >nul
rem Быстрая установка без exe — во все найденные версии Revit 2020–2026.
rem Рядом с этим файлом должны лежать папки R2020…R2026 с RevitAIClassifier.dll (или bin\Release после сборки)
rem и файл RevitAIClassifier.addin. Revit должен быть закрыт.
tasklist | find /i "Revit.exe" >nul && (echo Закройте Revit и запустите снова & pause & exit /b 1)
set "SRC=%~dp0"
if exist "%~dp0..\RevitAIClassifier\bin\Release\R2022" set "SRC=%~dp0..\RevitAIClassifier\bin\Release\"
set "ADDIN=%~dp0RevitAIClassifier.addin"
if not exist "%ADDIN%" set "ADDIN=%~dp0..\RevitAIClassifier\RevitAIClassifier.addin"
set /p URL="Адрес сервера АтрибутыАГР (Enter — http://SERVER:8765): "
if "%URL%"=="" set "URL=http://SERVER:8765"
set N=0
for %%v in (2020 2021 2022 2023 2024 2025 2026) do (
  if exist "%ProgramFiles%\Autodesk\Revit %%v" if exist "%SRC%R%%v\RevitAIClassifier.dll" (
    mkdir "%APPDATA%\Autodesk\Revit\Addins\%%v\RevitAIClassifier" 2>nul
    copy /y "%SRC%R%%v\RevitAIClassifier.dll" "%APPDATA%\Autodesk\Revit\Addins\%%v\RevitAIClassifier\" >nul
    copy /y "%ADDIN%" "%APPDATA%\Autodesk\Revit\Addins\%%v\" >nul
    if exist "%~dp0company_settings.json" copy /y "%~dp0company_settings.json" "%APPDATA%\Autodesk\Revit\Addins\%%v\RevitAIClassifier\" >nul
    > "%APPDATA%\Autodesk\Revit\Addins\%%v\RevitAIClassifier\service_url.txt" echo %URL%
    echo Установлено в Revit %%v
    set /a N+=1
  )
)
if %N%==0 echo Не найдено ни одной версии Revit с собранной dll.
echo Готово. Откройте Revit — вкладка «АтрибутыАГР».
pause
