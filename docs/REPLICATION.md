# Репликация на облачную БД Beget

Настройка логической репликации PostgreSQL: локальная БД (Docker) — источник (publisher), облачная БД `nipabtininstok.beget.app:5432` — подписчик (subscriber). Подключение идёт **от Beget к вашему серверу**: облачная БД создаёт subscription и подключается к вашему Postgres.

## Что сделано в репозитории

- **Конфиг логической репликации:** [config/postgres/replication.conf](../config/postgres/replication.conf) — параметры `wal_level=logical`, `max_replication_slots`, `max_wal_senders`, `listen_addresses`. В [docker-compose.yml](../docker-compose.yml) для сервиса `db` эти параметры применяются через `command`.
- **Публикация:** скрипт [scripts/setup_replication_publication.sql](../scripts/setup_replication_publication.sql) создаёт publication `ugc_pub` для всех таблиц. Выполнить один раз на локальной БД после перезапуска `db` с новым конфигом.

## Шаг 1. Запуск Postgres с поддержкой репликации

После изменений в `docker-compose.yml` перезапустите контейнер БД:

```bash
docker compose up -d db
```

Проверьте параметры:

```bash
docker compose exec db psql -U ugc -d ugc -c "SHOW wal_level;"
# ожидается: logical
```

## Шаг 2. Создание publication на локальной БД

Выполните скрипт один раз (из корня проекта):

```bash
docker compose exec db psql -U ugc -d ugc -f /dev/stdin < scripts/setup_replication_publication.sql
```

Или скопируйте скрипт в контейнер и выполните:

```bash
docker compose cp scripts/setup_replication_publication.sql db:/tmp/
docker compose exec db psql -U ugc -d ugc -f /tmp/setup_replication_publication.sql
```

Проверка: `docker compose exec db psql -U ugc -d ugc -c "\dRp+"` — должна быть публикация `ugc_pub`.

## Шаг 3. Доступ с сервера для Beget

Облачная БД Beget подключается **к вашему серверу**. Нужно:

1. **Сеть:** хост с Docker должен быть доступен из интернета по порту 5432 (или по другому порту с пробросом). Уточните у Beget исходящие IP или диапазоны и откройте для них порт в firewall (если используется).

2. **pg_hba.conf:** разрешить подключение с IP Beget для пользователя БД (того же, что в строке подключения для subscription). В Docker конфиг лежит в volume данных. Пример строки (подставьте реальный IP Beget и метод аутентификации):

   ```
   host    ugc    ugc    <BEGET_IP>/32    scram-sha-256
   ```

   Добавить можно так: смонтировать свой `pg_hba.conf` в `docker-compose` или после первого запуска отредактировать файл в volume и перезагрузить конфиг:

   ```bash
   docker compose exec db psql -U ugc -d ugc -c "SELECT pg_reload_conf();"
   ```

   Либо добавить строку в существующий файл (путь в контейнере: `/var/lib/postgresql/data/pg_hba.conf`) и выполнить `pg_reload_conf()`.

3. **listen_addresses:** уже задано `*` в конфиге репликации, Postgres слушает все интерфейсы.

## Шаг 4. Подготовка облачной БД Beget

На Beget должна быть БД с **той же схемой**, что и локальная:

- Либо выполнить миграции Alembic против Beget (если есть сетевой доступ с вашей стороны): задать `DATABASE_URL` на Beget и выполнить `alembic upgrade head`.
- Либо один раз восстановить только схему из дампа локальной БД (без данных или с данными — по необходимости).

Убедитесь, что на стороне Beget разрешены `CREATE SUBSCRIPTION` и исходящие подключения к внешнему Postgres (по документации/поддержке Beget).

## Шаг 5. Создание subscription на Beget

Подключитесь к облачной БД Beget и выполните (подставьте хост/порт/пользователь/пароль вашего сервера; пароль храните в секретах, не в коде):

```sql
CREATE SUBSCRIPTION ugc_sub
CONNECTION 'postgresql://<user>:<password>@<ВАШ_ПУБЛИЧНЫЙ_ХОСТ_ИЛИ_IP>:5432/ugc'
PUBLICATION ugc_pub
WITH (streaming = on);
```

- `<ВАШ_ПУБЛИЧНЫЙ_ХОСТ_ИЛИ_IP>` — FQDN или IP сервера, где крутится Docker, доступный с Beget.
- `streaming = on` (PostgreSQL 14+) уменьшает задержку применения изменений.

При первом создании подписки по умолчанию выполняется начальная копия данных (COPY). Если схема на Beget уже заполнена из дампа, создайте подписку с `copy_data = false`:

```sql
CREATE SUBSCRIPTION ugc_sub
CONNECTION '...'
PUBLICATION ugc_pub
WITH (streaming = on, copy_data = false);
```

## Проверка репликации

На Beget:

```sql
SELECT * FROM pg_stat_subscription;
```

На локальной БД (источник):

```sql
SELECT * FROM pg_stat_replication;
```

Проверка данных: вставьте тестовую строку в таблицу на источнике и убедитесь, что она появляется на реплике в течение нескольких секунд.

## Ограничения

- **Секвенции:** логическая репликация по умолчанию не реплицирует изменения `SEQUENCE`. Если нужны одинаковые значения на реплике — учитывайте ручную синхронизацию или особенности приложения.
- **Первичная загрузка:** при создании subscription с `copy_data = true` PostgreSQL сам выполняет начальную загрузку данных; при предзаполненной схеме используйте `copy_data = false`.

## Переменные окружения

Опциональные подсказки для строки подключения к издателю (для создания subscription на Beget) можно задать в [config/env.example](../config/env.example); пароли в репозиторий не помещайте.
