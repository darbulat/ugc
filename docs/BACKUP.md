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

## Point-in-Time Recovery (PITR) и репликация

Для восстановления на произвольный момент времени (например, за минуты до сбоя) и снижения потерь данных используется схема: **архивирование WAL** в S3 и периодические **базовые бэкапы** (pg_basebackup).

### Что это даёт

| Компонент | Назначение |
|-----------|------------|
| **WAL-архив** | PostgreSQL по `archive_command` загружает каждый готовый WAL-сегмент в S3 (префикс `wal_archive/`). Скрипт `scripts/archive_wal.py` вызывается из контейнера `db`. |
| **Базовый бэкап (pg_basebackup)** | Сервис `db_backup` по интервалу `BASE_BACKUP_INTERVAL_HOURS` создаёт снимок кластера и загружает его в S3 (`base_backup/`). Восстановление = развернуть этот снимок + применить WAL из архива до нужного времени. |
| **Репликация (replica)** | Опционально: вторая нода в режиме standby для быстрого failover; для PITR достаточно WAL-архива и базовых бэкапов. |

### Общая схема

```
[PostgreSQL primary db] --(archive_command)--> archive_wal.py --> S3 (wal_archive/)
       |
       +-- db_backup (периодически) --> pg_basebackup --> S3 (base_backup/)
```

### Включение PITR

1. В `.env` задайте те же S3-переменные, что и для обычных бэкапов: `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`.
2. Включите PITR и при необходимости задайте интервалы:
   ```env
   PITR_ENABLED=true
   BASE_BACKUP_INTERVAL_HOURS=24
   BASE_BACKUP_KEEP_DAYS=7
   ```
3. Пересоберите и перезапустите сервисы:
   ```bash
   docker compose build db
   docker compose up -d db db_backup
   ```
4. Сервис `db` собирается из `Dockerfile.db` (образ с Python и `archive_wal.py`). При `PITR_ENABLED=true` в команду Postgres добавляются `archive_mode=on` и `archive_command`, WAL начнёт выгружаться в S3.
5. Сервис `db_backup` при наличии `S3_ACCESS_KEY_ID` по истечении `BASE_BACKUP_INTERVAL_HOURS` дополнительно запускает `scripts/base_backup_db.py` и выгружает базовый бэкап в S3.

### Восстановление на момент времени (PITR)

Регламент выполняется вручную (или через скрипт `make restore-pitr`, см. ниже).

1. **Остановить приложение и PostgreSQL:**
   ```bash
   docker compose stop app app_2 admin migrate instagram_webhook kafka_consumer feedback_scheduler role_reminder_scheduler outbox_processor instagram_stats_scheduler instagram_stats_collector_scheduler db_backup
   docker compose stop pgbouncer db
   ```

2. **Скачать последний базовый бэкап из S3** в каталог, который будет использоваться как `PGDATA` (например, новый volume или пустой каталог на хосте). Ключ в S3: `base_backup/ugc_base_YYYYMMDD_HHMMSS.tar.gz`. Распаковать содержимое в каталог данных:
   ```bash
   # Пример: скачать через AWS CLI (path-style для Beget)
   aws --endpoint-url https://s3.ru1.storage.beget.cloud s3 cp s3://97596cccd207-ugc-s3/base_backup/ugc_base_YYYYMMDD_HHMMSS.tar.gz - | tar -xzf - -C /path/to/pgdata
   # Для формата pg_basebackup -Ft -z в архиве лежит base.tar.gz; распаковать его в PGDATA
   ```

3. **Создать в каталоге данных файл `postgresql.auto.conf`** (или добавить в `postgresql.conf`) параметры восстановления:
   - `restore_command` — команда, которая по имени WAL-файла (`%f`) скачивает его из S3 в путь `%p`. Пример для скрипта, который скачивает в текущий каталог:
     ```conf
     restore_command = 'aws --endpoint-url https://s3.ru1.storage.beget.cloud s3 cp s3://97596cccd207-ugc-s3/wal_archive/%f %p'
     ```
     (Путь к бакету и префикс `wal_archive/` должны совпадать с настройкой `archive_wal.py`.)
   - Опционально: `recovery_target_time = '2025-03-01 12:00:00'` — восстановиться до этого момента (по умолчанию — до последнего доступного WAL).

4. **Создать пустой файл `recovery.signal`** в каталоге данных (в PG 12+ это включает режим recovery при старте):
   ```bash
   touch /path/to/pgdata/recovery.signal
   ```

5. **Подмонтировать восстановленный каталог как данные `db`** (например, заменить volume или указать новый volume в compose) и запустить PostgreSQL:
   ```bash
   docker compose up -d db
   ```
   Postgres подтянет WAL из S3 и остановится на заданном времени (или на последнем сегменте). После успешного восстановления переименуйте или удалите `recovery.signal`, при необходимости отредактируйте конфиг и перезапустите остальные сервисы.

### Репликация (опционально)

- Отдельный сервис в Docker (например, `db_replica`) с тем же образом PostgreSQL.
- На primary уже заданы `wal_level=logical` и `max_wal_senders`; при необходимости добавьте `pg_hba.conf` для подключения реплики.
- Реплика даёт быстрый failover, но для защиты от логических ошибок и удаления данных по-прежнему нужны бэкапы и PITR.

## Рекомендации для production

1. **Внешнее хранилище**: Включите S3 (см. выше) или настройте выгрузку в другое хранилище.
2. **Мониторинг**: Включён алерт **BackupWALArchiverFailed** (группа `backups` в `config/monitoring/alerts.yml`): срабатывает при сбое архивирования WAL (метрика postgres_exporter `pg_stat_archiver_failed_total`). Дополнительно рекомендуется: алерты на отсутствие новых бэкапов (логические дампы в `backups/`, при PITR — появление новых объектов в S3 в `base_backup/` и актуальность WAL в `wal_archive/`), оповещения при падении сервиса `db_backup` или ошибках в логах архивирования WAL.
3. **Тестирование восстановления**: Регулярно проверяйте восстановление из логического бэкапа и при PITR — из базового бэкапа + WAL до тестового момента времени.
4. **Шифрование**: Рассмотрите возможность шифрования бэкапов для чувствительных данных.
5. **Point-in-Time Recovery**: Для критичных систем включите PITR (`PITR_ENABLED=true`) и задайте S3-переменные; убедитесь, что базовые бэкапы и WAL успешно пишутся в S3.

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
