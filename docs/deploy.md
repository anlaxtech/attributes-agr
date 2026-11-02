# Сервис на сервере (Docker)

## Установка из готового образа (проще)

```bash
mkdir atributy-agr && cd atributy-agr && mkdir data
# скачайте deploy/docker-compose.image.yml из репозитория, замените <владелец>
# положите в data: rules.xlsx (таблица правил из релиза), labels.xlsx, labels_spaces.xlsx
docker compose -f docker-compose.image.yml up -d
```

Обновление: `docker compose -f docker-compose.image.yml pull && docker compose -f docker-compose.image.yml up -d`.

## Установка из исходников

```bash
git clone https://github.com/<владелец>/atributy-agr.git
cd atributy-agr/deploy
mkdir -p data
cp ../rules/Правила_АГР.xlsx data/rules.xlsx
# + data/labels.xlsx и data/labels_spaces.xlsx из программы обучения (можно позже)
docker compose up -d --build
```

Проверка: `http://<сервер>:8765/health` → `"ok": true`.

Если с других компьютеров не открывается — откройте порт (Windows, от администратора):

```
netsh advfirewall firewall add rule name="AtributyAGR 8765" dir=in action=allow protocol=TCP localport=8765
```

Порт занят — поменяйте левое число в `ports` (`"8770:8765"`) и адрес в плагине.

## Настройки (`docker-compose.yml`)

| Переменная | По умолчанию | Что |
|---|---|---|
| `AGR_RULES` | `/data/rules.xlsx` | таблица правил |
| `AGR_LABELS` | `/data/labels.xlsx` | разметка элементов |
| `AGR_SPACE_LABELS` | `/data/labels_spaces.xlsx` | разметка помещений и зон |
| `AGR_RELOAD_SEC` | `30` | как часто проверять изменения таблиц (0 — не проверять) |
| `AGR_MODE` | `hybrid` | `rules` — только правила, `model` — только модель |
| `AGR_TOKEN` | пусто | если задан — запросы без `X-AGR-Token` отклоняются |

## Обновление данных и кода

| Что поменяли | Что сделать |
|---|---|
| таблицы в `data` | ничего — сервис подхватит сам за ~30 с (видно в `/health` → `loaded_at`) |
| код (`git pull`) | `docker compose up -d --build` |

Если таблица битая или была открыта в Excel при копировании, сервис продолжит работать на прежней
версии, а ошибка будет в `/health` → `last_error`.

Готовый образ из релизов: `ghcr.io/<владелец>/atributy-agr-service:latest` — можно указать его в
`image:` вместо `build:`.

## Полезное

```bash
docker compose logs -f        # журнал
docker compose restart        # перезапуск
```

Правки пользователей копятся в `data/corrections.csv`.
