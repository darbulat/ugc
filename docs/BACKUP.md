# Резервное копирование базы данных

Система автоматического резервного копирования PostgreSQL настроена и работает через Docker Compose.

## Автоматическое резервное копирование

Сервис `db_backup` автоматически создает резервные копии базы данных с заданным интервалом.

### Настройка

Переменные окружения в `.env`:

- `BACKUP_KEEP_DAYS` - количество дней хранения бэкапов (по умолчанию: 7)
- `BACKUP_INTERVAL_HOURS` - интервал между бэкапами в часах (по умолчанию: 24)

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

## Рекомендации для production

1. **Внешнее хранилище**: Настройте синхронизацию бэкапов во внешнее хранилище (S3, NFS, etc.)
2. **Мониторинг**: Добавьте алерты на отсутствие новых бэкапов
3. **Тестирование восстановления**: Регулярно проверяйте возможность восстановления из бэкапов
4. **Шифрование**: Рассмотрите возможность шифрования бэкапов для чувствительных данных
5. **Point-in-Time Recovery**: Для критичных систем рассмотрите настройку WAL архивирования

## Пример настройки синхронизации с S3

Можно добавить скрипт для синхронизации с S3 после создания бэкапа:

```bash
# В scripts/backup_db.py добавить вызов после создания бэкапа
aws s3 cp "$backup_path" "s3://your-bucket/backups/$(basename $backup_path)"
```

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
