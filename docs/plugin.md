# Плагин Revit

## Поддерживаемые версии

| Revit | Платформа | Папка сборки |
|---|---|---|
| 2020 | .NET Framework 4.7 | `bin/Release/R2020` |
| 2021–2024 | .NET Framework 4.8 | `bin/Release/R2021` … `R2024` |
| 2025–2026 | .NET 8 | `bin/Release/R2025`, `R2026` |

Код один; различия версий собраны в `Services/Compat.cs` (ID элементов, JSON, открытие файлов).

## Сборка

Нужно: Windows и **.NET SDK 8** (https://dotnet.microsoft.com) — он собирает и .NET Framework, и .NET 8.
Visual Studio 2022 — по желанию.

- **Все версии:** `plugin/RevitAIClassifier/build_all.bat`.
- **Одна версия:** `dotnet build plugin/RevitAIClassifier/RevitAIClassifier.csproj -c Release -p:RevitVersion=2024`.
- **Visual Studio:** открывается как обычно и собирает версию по умолчанию (2022); другую — свойство `RevitVersion`.

RevitAPI берётся из установленного Revit этой версии (`C:\Program Files\Autodesk\Revit 20xx`), а если его нет —
автоматически из NuGet (`Nice3point.Revit.Api.*`). Поэтому все семь версий можно собрать на одном компьютере.

Если Revit этой версии установлен, после сборки dll и `.addin` сами копируются в
`%AppData%\Autodesk\Revit\Addins\20xx` — закройте Revit перед сборкой.

## Установщик для пользователей

Один установщик на все версии: ставит плагин в те Revit 2020–2026, которые найдёт на компьютере.

1. Inno Setup 6 (бесплатно): https://jrsoftware.org/isdl.php
2. Соберите плагин: `build_all.bat` (версии без собранной dll установщик просто пропустит).
3. По желанию: в Revit «Экспорт настроек» → `plugin/installer/company_settings.json`
   (готовый маппинг для всех; в git не попадает).
4. `ISCC.exe /DDefaultUrl=http://my-server:8765 /DAppVer=1.4 plugin\installer\RevitAIClassifier.iss`
   → `plugin/installer/output/AtributyAGR_Revit2020-2026_Setup_1.4.exe`.

Пользователь: закрыть Revit → установить (права администратора не нужны) → вкладка **АтрибутыАГР**.
Новая версия ставится поверх, настройки сохраняются (они общие для всех версий Revit).

Без exe: `plugin/installer/install.bat` — после `build_all.bat` можно запускать прямо из репозитория.

## Работа

1. **Маппинг:** слева категории (галочки — что заполнять), справа параметр АГР ↔ параметр Revit
   (поиск, тип/экземпляр), «Перезаписывать» — менять ли уже заполненное.
   Внизу: весь документ / активный вид, тип фасада, адрес сервера.
2. **«Заполнить параметры»** → окно проверки: вкладки 1–5, «проверить» вверху,
   группы помещений и моделей в контексте (▸ раскрыть), выбор кода с поиском.
3. **«Пересчитать следующие шаги»** — после правки на шаге.
4. **«Записать в Revit»** → отчёт в Excel (ID элементов, что заполнено и почему нет).

## Настройки пользователя

`%AppData%\RevitAIClassifier\settings.json`: маппинг, `ServiceUrl`, `ServiceToken`
(если на сервере задан `AGR_TOKEN`), типы фасада по файлам. Экспорт/импорт — кнопками в окне.
