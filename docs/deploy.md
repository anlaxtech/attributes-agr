# Сервис на сервере (Docker)

## Установка из готового образа

Чтобы скачать закрытый образ `ghcr.io/anlaxtech/atributy-agr-service:latest`, войдите командой
`docker login ghcr.io` под учётной записью с доступом к пакету. Для входа используйте
[токен GitHub (classic) с правом `read:packages`](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#authenticating-with-a-personal-access-token-classic).
Если доступа к пакету нет, [соберите сервис из исходников](#установка-из-исходников).

```bash
mkdir attributes-agr && cd attributes-agr && mkdir data
# скачайте deploy/docker-compose.image.yml из репозитория в текущую папку
# скопируйте rules/Правила_АГР.xlsx в data/rules.xlsx
# разметку labels.xlsx и labels_spaces.xlsx можно добавить позже
docker compose -f docker-compose.image.yml up -d
```

Обновление: `docker compose -f docker-compose.image.yml pull && docker compose -f docker-compose.image.yml up -d`.

## Установка из исходников

```bash
git clone https://github.com/anlaxtech/attributes-agr.git
cd attributes-agr/deploy
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
| `AGR_TOKEN` | пусто | при пустом значении проверка выключена. Если токен задан, каждый запрос, кроме `/health`, требует совпадающий `X-AGR-Token` |

## Обновление данных и кода

| Что поменяли | Что сделать |
|---|---|
| таблицы в `data` | ничего — сервис подхватит сам за ~30 с (видно в `/health` → `loaded_at`) |
| код (`git pull`) | `docker compose up -d --build` |

Если таблица битая или была открыта в Excel при копировании, сервис продолжит работать на прежней
версии, а ошибка будет в `/health` → `last_error`.

## Полезное

```bash
docker compose logs -f        # журнал
docker compose restart        # перезапуск
```

Правки пользователей копятся в `data/corrections.csv`.
