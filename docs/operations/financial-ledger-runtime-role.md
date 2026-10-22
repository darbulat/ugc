# Task18: ledger foundation — НЕ разрешение на активацию

Миграция `financial_ledger` после `financial_items` добавляет только пустые
таблицы. Никакого импорта legacy decimal/float, fictitious user 0, подтверждения
банка или суммирования валют. Проекция не обновляется этим адаптером: сервисы
issue/transfers/replay/payout относятся к следующим задачам и выключены.

## Разделение полномочий — обязательный production readiness gate

Production роли этим PR НЕ создаются и не изменяются. Миграции выполняет
отдельный owner; runtime должен быть NOSUPERUSER/NOCREATEROLE/NOBYPASSRLS,
не владельцем схемы/таблиц/функций, без членства в owner/migration ролях,
без CREATE в доверенных схемах и без возможности менять session_replication_role.
Приложению нельзя выдавать migration credentials.

DBA должен отдельно проверить фактические grants, inherited/default privileges:
- на financial_obligations, rate_snapshots, financial_movements,
  financial_audit_events: только SELECT, INSERT;
- на financial_wallets: SELECT, INSERT, UPDATE (проекция), не DELETE/TRUNCATE;
- на users для общего mutex нужны SELECT и UPDATE privilege; выдавать только
  минимально согласованные права. Порядок: UUID-sorted users FOR NO KEY UPDATE,
  затем sorted recipient+currency wallets, затем items/obligations/requests.

Не применять blanket GRANT ALL и не предоставлять runtime ownership. SQL
statement triggers дополнительно запрещают UPDATE/DELETE/TRUNCATE immutable
таблиц, включая CASCADE и пустые таблицы. Изменение истории — новая операция.
Owner технически может снять trigger; его credentials — отдельная trust boundary.

Тесты создают UUID-named NOLOGIN non-owner NOSUPERUSER роль, реально выполняют
SET LOCAL ROLE, проверяют SQLSTATE 42501 для DML/ALTER и trigger rejection даже
при избыточных DML grants. Cleanup затрагивает только созданную роль и UUID-схемы.
Тестовый superuser используется исключительно для владения isolated test contour.

## Контракты и границы

Все репозитории требуют активную caller AsyncSession; commit/rollback остаются
у caller. Retry возвращает первую сохранённую запись, включая recorded_at и id.
Hash: sorted compact UTF-8 JSON, UUID strings, UTC microsecond timestamps,
исключены storage id, recorded_at, payload_hash. Виды client/creator принимаются
как storage aliases client_referral/creator_referral ДО hash и записи. Side
snapshot остаётся client/creator; system actor — именованный producer без UUID.
Actor provenance не является авторизацией.

Конфликт hash вызывает ValueError; вызывающая command boundary должна надёжно
сохранить incident/audit, в том числе при rollback всей business transaction.
Внутри адаптера нет отдельного commit для обхода атомарности.

Allocation/execution/refund/case UUID — типизированные ссылки на будущие сущности,
пока без FK к несуществующим таблицам задач 19–24+. Это НЕ доказательство банка,
не разрешение резервировать/выплачивать; до их реализации обязательны реальные
FK/scope checks, подтверждение банка и replay reconciliation. Request FK относится
к существующему payout_requests, без изменения legacy payout API.

Перед активацией также нужны command authorization, durable incident boundary,
проверка всех legacy/v1 writers, version-aware cutoff и approved legal/policy
inputs. Никакого gate enable этим PR. При наличии ЛЮБЫХ новых данных downgrade
отказывается до DDL. Пустая миграция обратима; destructive truncate не является
поддерживаемым способом подготовки downgrade.
