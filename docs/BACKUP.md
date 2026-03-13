# Резервное копирование базы данных

Система автоматического резервного копирования PostgreSQL настроена и работает через Docker Compose.

## Автоматическое резервное копирование

Сервис `db_backup` автоматически создает резервные копии базы данных с заданным интервалом.

### Настройка

Переменные окружения в `.env`:

- `BACKUP_KEEP_DAYS` - количество дней хранения бэкапов (по умолчанию: 7)
- `BACKUP_INTERVAL_HOURS` - интервал между бэкапами в часах (по умолчанию: 24)

Параметры подключения к БД: при наличии переменных `POSTGRES_*` они имеют приоритет над `DATABASE_URL` (так в Docker бэкап всегда использует те же учётные данные, что и сервис `db`). Иначе используются хост/порт/БД/пользователь/пароль из `DATABASE_URL`. В `.env` обязательно задайте `POSTGRES_PASSWORD` тем же значением, с которым инициализирован контейнер `db`.

### Запуск

Сервис автоматически запускается при старте Docker Compose:

```bash
docker compose up -d
```

Бэкапы сохраняются в Docker volume `backup_data` и доступны внутри контейнера `db_backup` по пути `/backups`.

## Ручное управление бэкапами

### Создание бэкапа вручную

```bash
make backup-db
```

Или напрямую через Docker:

```bash
docker compose run --rm db_backup python scripts/backup_db.py \
    --host db \
    --port 5432 \
    --database ugc \
    --user ugc \
    --password <password> \
    --output-dir /backups
```

### Просмотр списка бэкапов

```bash
make list-backups
```

Или напрямую:

```bash
docker compose run --rm db_backup ls -lh /backups/
```

### Восстановление из бэкапа

**ВНИМАНИЕ:** Восстановление перезапишет текущую базу данных!

```bash
make restore-db BACKUP_FILE=/backups/ugc_backup_20240206_020000.sql.gz
```

Или напрямую:

```bash
docker compose run --rm db_backup python scripts/restore_db.py \
    --host db \
    --port 5432 \
    --database ugc \
    --user ugc \
    --password <password> \
    --confirm \
    /backups/ugc_backup_20240206_020000.sql.gz
```

## Формат файлов бэкапа

Бэкапы сохраняются в формате:
- Имя файла: `ugc_backup_YYYYMMDD_HHMMSS.sql.gz`
- Формат: сжатый SQL дамп (gzip)
- Содержимое: полный дамп базы данных с командами для очистки существующих объектов

## Ротация бэкапов

Старые бэкапы автоматически удаляются при создании нового бэкапа, если они старше значения `BACKUP_KEEP_DAYS`.

## Доступ к бэкапам из хоста

Для доступа к бэкапам с хоста можно использовать:

```bash
# Копирование бэкапа на хост
docker compose cp db_backup:/backups/ugc_backup_20240206_020000.sql.gz ./backups/

# Или монтирование volume напрямую (требует настройки)
```

## Выгрузка бэкапов в S3

После создания локального бэкапа скрипт может автоматически загружать его в S3-совместимое хранилище (например, Beget). Используется path-style endpoint.

### Переменные окружения

В `.env` задайте:

- `S3_BACKUP_ENABLED` — включить выгрузку в S3 (`true` / `false`, по умолчанию `false`)
- `S3_ENDPOINT_URL` — URL S3 API (по умолчанию: `https://s3.ru1.storage.beget.cloud`)
- `S3_BUCKET` — имя бакета (по умолчанию: `97596cccd207-ugc-s3`)
- `S3_ACCESS_KEY_ID` — ключ доступа (обязательно при включённом S3)
- `S3_SECRET_ACCESS_KEY` — секретный ключ (обязательно при включённом S3)

Файлы в S3 сохраняются по ключу `backups/ugc_backup_YYYYMMDD_HHMMSS.sql.gz`. Старые объекты в S3 удаляются по тем же правилам, что и локальные бэкапы (`BACKUP_KEEP_DAYS`).

### Пример для Beget

1. Создайте бакет и получите ключи доступа в панели Beget.
2. Path style: `https://s3.ru1.storage.beget.cloud/97596cccd207-ugc-s3` — в коде используется path-style автоматически.
3. В `.env`:
   ```env
   S3_BACKUP_ENABLED=true
   S3_ENDPOINT_URL=https://s3.ru1.storage.beget.cloud
   S3_BUCKET=97596cccd207-ugc-s3
   S3_ACCESS_KEY_ID=<ваш_ключ>
   S3_SECRET_ACCESS_KEY=<ваш_секрет>
   ```
4. Перезапустите сервис: `docker compose up -d db_backup`.

### Восстановление из S3

Скрипт `restore_db.py` может восстанавливать базу напрямую из S3, без предварительной выгрузки файла на диск.

Переменные окружения (те же, что для выгрузки): `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`.

**Список бэкапов в S3:**

```bash
docker compose run --rm -e S3_ACCESS_KEY_ID=... -e S3_SECRET_ACCESS_KEY=... \
    db_backup python scripts/restore_db.py --list-s3
```

**Восстановление из S3 по ключу объекта:**

```bash
docker compose run --rm db_backup python scripts/restore_db.py \
    --host db --port 5432 --database ugc --user ugc --password <password> \
    --from-s3 --confirm backups/ugc_backup_20240206_020000.sql.gz
```

Можно указать только имя файла (префикс `backups/` подставится автоматически):

```bash
docker compose run --rm db_backup python scripts/restore_db.py \
    --from-s3 --confirm ugc_backup_20240206_020000.sql.gz
```

### Восстановление из бэкапа, скачанного из S3 вручную

1. Скачайте файл из S3 (через панель Beget, AWS CLI или другой клиент), например в `./backups/ugc_backup_20240206_020000.sql.gz`.
2. Скопируйте в контейнер или смонтируйте каталог и выполните восстановление:
   ```bash
   docker compose run --rm -v ./backups:/backups db_backup python scripts/restore_db.py \
       --host db --port 5432 --database ugc --user ugc --password <password> \
       --confirm /backups/ugc_backup_20240206_020000.sql.gz
   ```

## Point-in-Time Recovery (PITR)

PITR позволяет восстановить базу данных на произвольный момент времени с точностью до транзакции. Полезно для отката после ошибочного DELETE/UPDATE или восстановления после сбоя с минимальной потерей данных.

### Архитектура

```
[PostgreSQL db] --(archive_command: cp)--> [wal_archive volume] <--(читает)--> [db_backup сервис]
                                                                                     |
                                                                              [uploads to S3]
                                                                                     |
                                                    S3: wal_archive/ + base_backups/ + backups/
```

| Компонент | Назначение |
|-----------|------------|
| **archive_command** | PostgreSQL копирует завершённые WAL-сегменты в Docker volume `wal_archive` |
| **archive_timeout** | Принудительная смена WAL-сегмента каждые 60 секунд (минимизирует потерю при низкой нагрузке) |
| **wal_uploader.py** | Сайдкар в `db_backup` каждые 5 минут загружает WAL из volume в S3 (`wal_archive/`) |
| **base_backup.py** | Периодический `pg_basebackup` (при каждом цикле бэкапа), результат в S3 (`base_backups/`) |
| **pitr_restore.py** | Скачивает base backup + WAL из S3, настраивает recovery и готовит к запуску |

### Включение PITR

PITR включён по умолчанию (`PITR_ENABLED=true`). Для работы WAL-загрузки в S3 также должен быть включён S3:

```env
PITR_ENABLED=true
S3_BACKUP_ENABLED=true
S3_ACCESS_KEY_ID=<ваш_ключ>
S3_SECRET_ACCESS_KEY=<ваш_секрет>
```

WAL-архивирование на уровне PostgreSQL (`archive_mode=on`) работает всегда — даже без S3 WAL копируются в Docker volume `wal_archive`.

### Что делает backup_loop.sh

При каждом цикле (по умолчанию каждые 12 часов):

1. **pg_dump** — логический бэкап (как раньше), загрузка в S3
2. **pg_basebackup** — физический снимок кластера, загрузка в S3 (`base_backups/`)
3. **wal_uploader.py** — загрузка накопившихся WAL-сегментов в S3 (`wal_archive/`)

Дополнительно WAL загружается каждые 5 минут в фоновом режиме.

### Ручные операции

```bash
# Создать base backup вручную
make base-backup

# Загрузить WAL в S3 вручную
make upload-wal

# Список base backup'ов в S3
make list-base-backups-s3
```

### Восстановление на момент времени

Скрипт останавливает все сервисы, восстанавливает БД из S3 и перезапускает стек. Root-доступ к хосту не нужен — всё работает через Docker.

```bash
# Посмотреть доступные base backup'ы в S3
make list-base-backups-s3

# Восстановить на текущий момент (последний доступный)
make pitr-restore

# Восстановить на конкретный момент времени
make pitr-restore TARGET_TIME="2026-03-13 10:00:00"
```

Скрипт автоматически:
1. Останавливает все сервисы (app, admin, pgbouncer, schedulers, kafka и т.д.)
2. Очищает PGDATA
3. Скачивает base backup + WAL из S3
4. Настраивает recovery (без лишних шагов вручную)
5. Запускает PostgreSQL в режиме recovery
6. Дожидается готовности и перезапускает все сервисы
7. Печатает `pg_is_in_recovery()` для подтверждения

### Структура S3

```
s3://bucket/
├── backups/              # Логические pg_dump бэкапы
│   └── ugc_backup_YYYYMMDD_HHMMSS.sql.gz
├── base_backups/         # Физические pg_basebackup снимки
│   └── ugc_basebackup_YYYYMMDD_HHMMSS.tar.gz
└── wal_archive/          # WAL-сегменты
    └── 000000010000000000000001
```

### Ротация

Все артефакты (логические бэкапы, base backup'ы, WAL-файлы) ротируются по `BACKUP_KEEP_DAYS` (по умолчанию 7 дней) — как локально, так и в S3.

## Рекомендации для production

1. **Внешнее хранилище**: Включите S3 (см. выше) или настройте выгрузку в другое хранилище.
2. **Мониторинг**: Добавьте алерты на отсутствие новых бэкапов.
3. **Тестирование восстановления**: Регулярно проверяйте возможность восстановления из бэкапов.
4. **Шифрование**: Рассмотрите возможность шифрования бэкапов для чувствительных данных.
5. **Point-in-Time Recovery**: Для критичных систем настройте WAL-архивирование и базовые бэкапы по схеме выше.

## Troubleshooting

### Бэкап не создается

1. Проверьте логи сервиса:
   ```bash
   docker compose logs db_backup
   ```

2. Убедитесь, что сервис запущен:
   ```bash
   docker compose ps db_backup
   ```

3. Проверьте переменные окружения:
   ```bash
   docker compose exec db_backup env | grep POSTGRES
   ```

### Ошибка доступа к базе данных

Убедитесь, что:
- Сервис `db` запущен и здоров
- Переменные `POSTGRES_*` правильно настроены в `.env`
- Сеть Docker позволяет `db_backup` подключаться к `db`
