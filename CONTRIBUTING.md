# Участие в разработке

Спасибо за интерес к АтрибутыАГР!

## Как предложить изменение

1. Issue — опишите проблему или идею (для ошибок: версия Revit, версия плагина, что делали, что ожидали).
2. Fork → ветка → изменения → Pull Request в `main`.
3. CI должен быть зелёным.

## Локальная проверка

```bash
pip install -r requirements-dev.txt
pytest -q                                   # сервис и правила
dotnet build plugin/RevitAIClassifier/RevitAIClassifier.csproj -c Release -p:UseRevitNuGet=true
docker build -t atributy-agr-service python
```

## Правила кода

- Python: понятные имена, комментарии и сообщения пользователю — по-русски.
- C#: .NET Framework 4.8 (Revit 2022), без сторонних DLL в плагине (кроме Revit API).
- Новое правило заполнения — в таблицу `rules/Правила_АГР.xlsx`, а не в код.
- Не коммитьте данные проектов: IFC, разметку, журналы правок, адреса серверов.

## Проверка правил на своих данных

`python python/check_rules.py rules/Правила_АГР.xlsx <папка_с_ifc>` — в описание PR приложите,
как изменились покрытие и совпадения.
