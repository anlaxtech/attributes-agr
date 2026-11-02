@echo off
chcp 65001 >nul
for %%v in (2020 2021 2022 2023 2024 2025 2026) do (
  del /q "%APPDATA%\Autodesk\Revit\Addins\%%v\RevitAIClassifier.addin" 2>nul
  rmdir /s /q "%APPDATA%\Autodesk\Revit\Addins\%%v\RevitAIClassifier" 2>nul
)
echo Плагин удалён из Revit 2020–2026. Настройки пользователя остались в %APPDATA%\RevitAIClassifier
pause
