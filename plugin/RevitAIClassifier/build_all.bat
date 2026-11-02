@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Сборка плагина под Revit 2020–2026 подряд. Результат: bin\Release\R20xx\RevitAIClassifier.dll
rem Нужен .NET SDK 8 (https://dotnet.microsoft.com) — он собирает и .NET Framework, и .NET 8.
set FAILED=
for %%v in (2020 2021 2022 2023 2024 2025 2026) do (
  echo.
  echo ===== Revit %%v =====
  dotnet build RevitAIClassifier.csproj -c Release -p:RevitVersion=%%v -nologo -v:minimal || set FAILED=%FAILED% %%v
)
echo.
if defined FAILED (echo Не собрались версии:%FAILED% & pause & exit /b 1)
echo Готово: bin\Release\R2020 … R2026
pause
