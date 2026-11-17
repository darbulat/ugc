# UMC Financial v1 Implementation Plan

**Версия плана: 1.1 — уточнён после независимого read-only ревью.** Этот файл заменяет ранее отправленную редакцию плана; нормативная спецификация остаётся1.2.

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.
> Если этот навык недоступен, до начала исполнения выбрать доступный эквивалент: небольшая задача → независимая проверка соответствия → проверка качества. Не считать неизвестный навык установленным.

**Goal:** реализовать принятую спецификацию UMC Financial v1 версии 1.2, сначала стабилизировав текущий контур, затем включив новое финансовое ядро на ограниченном пилоте.

**Architecture:** сохраняется Hexagonal Architecture. Legacy и v1 разделяются policy_version, источниками обязательств и writer barrier; v1 использует integer minor units, immutable journal, явную доставку и общий payout gate. Бизнес-команды общие для Telegram/MAX/Mini App/admin; события и изменения БД атомарны, сетевые вызовы вне locks.

**Tech Stack:** Python 3.13, SQLAlchemy, PostgreSQL 16/PostGIS, Alembic, FastAPI, aiogram, Kafka/outbox, Redis, pytest, Ruff, mypy и Playwright.

---

## Короткий маршрут

- **Начало:** Tasks01–02 — измерить baseline, восстановить coverage≥98% без снижения порога и добавить изолированный PostgreSQL в CI.
- **Релиз A:** Tasks03–10 — закрыть права менеджеров, конфликт feedback, legacy payout safety-stop, ошибки доставки, reconciliation и повторы оплаты. Выпускается независимо от финансового расширения.
- **Релиз B:** Tasks11–49 — policy/items → ledger → snapshots → доставка/сотрудничество/споры → сопровождение/возвраты → payout → API/UI → migration bridge → пилотная готовность.
- **Релиз C:** Tasks50–52 — дополнительные соцсети и кабинет/дизайн; после B, по отдельным входным данным.
- **До денежных включений:** заполнить параметры принятой policy, получить реальный операционный/юридический sign-off, проверить общий legacy/v1 gate и rollback. Утверждение спецификации не включает flags автоматически.
- **Проверяемый объём:** 52 карточки задач, 18 будущих PR-пакетов, трассировка всех 52 AC. Это не оценка в рабочих днях и не 18 уже открытых PR.

## 0. Статус и исходные данные

- Это **только план**, не реализация, не разрешение на production migration, commit/push/merge/deploy. На момент создания изменяется только этот Markdown-файл в `.hermes/plans/`.
- Рабочий репозиторий `/opt/myapp/ugc`; исходный app HEAD `8a59b3d756fad1be77d9a7ea3e88745be455472c`, main.
- Нормативная спецификация: `docs/superpowers/specs/2026-10-22-umc-financial-v1-spec.md`, **версия 1.2**, commit `fd784a471a00fc4d99acca22d69a787dfe19527e`, PR https://github.com/darbulat/ugc/pull/147. Она пока в ветке `docs/umc-financial-v1-spec`, не в текущем main.
- Локальная копия спецификации: `/opt/myapp/ugc/.hermes/plans/2026-10-22_125555-umc-financial-v1-spec.md`.
- Десять D-xx **приняты**: повторно не запрашивать те же продуктовые решения. Длительность возвратного окна/selection_due_at/формальные условия выплат остаются обязательными входными параметрами; не придумывать их.
- Исторический CI предыдущего docs commit: 3660 passed, 19 skipped, 18 deselected; workflow failure по coverage **97.41% < 98%**. Это не новый baseline текущей ветки; результаты каждого будущего PR измеряются заново.
- Изучены CLAUDE.md, Makefile, docker-compose.test.yml, tests/conftest.py, tests/integration/conftest.py, существующие services/API/outbox/container. Важное отличие: tests/integration/conftest.py создаёт SQLite и исключает некоторые PostgreSQL-таблицы; существующий каталог с названием integration не доказывает row locks/unique indexes реальной БД.

## 1. Неизменяемые решения и границы

1. Client snapshot при capture; creator snapshot = max(активное назначение, capture), новый snapshot при замене. Год от referred user, calendar anniversary UTC, 29 февраля→28 февраля.
2. Стандарт selection 50000 RUB minor; accompaniment 120000; management 60000 только за успешную оплаченную работу. Referral база только selection, не весь платёж.
3. Available клиенту по item после его refund window и ещё14 суток hold. Автору/менеджеру после success_final+14 суток. Разные основания не смешивать.
4. 72 часа только от достоверной delivery; unknown recovery даёт полное окно, не backdating. Explicit confirm допустим при соответствующих правах/версии.
5. Авторский грейд10/12/15/20% при0/100/200/400 verified уникальных авторов, затем3% со второго года; клиент10%, затем3%. Новые overrides/нестандартные цены выключены D-07, legacy override не переносится молча.
6. Partial refund/replacement, деньги после paid и банковское unknown идут через связанные корректировки/case, не редактирование истории, не автоматическое взыскание из новых доходов.
7. В MVP payout на весь доступный остаток одной валюты; reserve в одной transaction; SLA72h не TTL. Никаких6%, сгорания и автоматических банковских API.
8. D-08 только новые разрешённые orders после технического cutover; созданные раньше, даже неоплаченные, остаются legacy. Откат бинарника без writer barrier запрещён.
9. Все имена **Create** ниже — проектируемые, не утверждение об уже существующих файлах. Номера Alembic revisions не задаются заранее.
10. C отдельно: соцсети/дизайн не блокируют исправления A и финансовый пилот B.

## 2. Порядок PR и зависимости

PR здесь — **будущие границы review**, не уже созданные pull requests. Каждый PR зелёный и merge отдельно по разрешению; production deploy не следует автоматически из merge документа.

| Пакет | Содержание | Зависит от |
|---|---|---|
| PR-00 | baseline ≥98% и настоящий изолированный PostgreSQL в CI | принятая спецификация, разрешение на код |
| PR-01 | права конкретной manager–creator пары | PR-00 |
| PR-02 | feedback conflicts, доставка, актуальный менеджер | PR-00/01 |
| PR-03 | reconciliation, constraints и legacy idempotence/races | PR-00 |
| PR-04 | v1 money/policy/ADR, flags off | PR-00/02 |
| PR-05 | items/capture/assignments | PR-03/04 |
| PR-06 | immutable ledger/replay | PR-04/05 |
| PR-07 | verified grades/snapshots/replacements | PR-05/06 |
| PR-08 | typed routing/inbox/durable delivery | PR-06 |
| PR-09 | selection fulfilment/collaboration/disputes/hold | PR-07/08 |
| PR-10 | оплаченные management entitlements | PR-09 |
| PR-11 | component refunds и disputed debt | PR-09/10 |
| PR-12 | общий legacy/v1 gate, reserve, ручное исполнение | PR-06/09/11 |
| PR-13 | DI/API, меню/checkout и digest | PR-07–12 |
| PR-14 | dry-run bridge, writer barrier и rollback | PR-12/13 |
| PR-15 | admin/alerts, synthetic E2E, release checklist | PR-14 |
| PR-16 | social accounts и registration extensions — C | после принятия B |
| PR-17 | визуальное обновление и расширенный кабинет — C | PR-16 и реальные tokens |

Назначение PR-14 в конце не разрешает включать финансовый write path раньше writer barrier: все предыдущие v1 producers/reserve/execution выключены flags до полного Gate B. Tasks содержат более точные зависимости, чем укрупнённая таблица. Не объединять ветки, которые одновременно меняют models.py/ports/container, без integration review.

## 3. Безопасная среда и команды будущего исполнения

Команды ниже **не выполнялись при написании плана**. Запускать из отдельного development checkout без production `.env` и без доступа к рабочим tokens/DB.

### 3.1. Микроцикл для каждого изменения

Один шаг занимает ориентировочно2–5 минут; карточка может содержать несколько циклов. Каждый завершённый PR запускается с flags off и не содержит production NotImplementedError/TODO-денежных путей: до готового adapter используется явный fail-closed, не фиктивный success. Если minimal implementation не помещается в понятный маленький diff — разрезать на ещё один test→change, а не писать полсервиса до первого GREEN.

1. Написать **один** новый тест одного поведения, используя реальный service/repo; fake только внешние границы.
2. RED: выполнить точный selector и увидеть ожидаемый assertion failure от текущего поведения. Ошибка импорта из-за опечатки/неподнятой БД не считается доказательством. Для отсутствующего нового символа сначала согласовать контракт и минимальный каркас, затем получить поведенческий RED без production логики.
3. GREEN: минимальная реализация только этого поведения.
4. Повторить selector, затем весь target file и соседние legacy тесты.
5. Следующий edge case — отдельный такой же цикл, не все тесты и вся реализация горизонтально.
6. После завершения маленького reviewable изменения — refactor; полный quality gate на границе PR. Коммиты только при будущем разрешении на реализацию; в этом planning turn их нет.

Для unit-задач в изолированном checkout:

```bash
# Вначале uv sync --all-extras, затем безопасные test-only env.
# Эти значения — только искусственные fixtures, не действующие credentials.
# Обязательно ДО любого pytest/coverage: не наследовать cleanup URL/live E2E.
for name in ${!E2E_@} ${!TELEGRAM_E2E_@} ${!MAX_E2E_@}; do
  unset "$name"
done
unset PYTEST_ADDOPTS
export BOT_TOKEN=test-token
export DATABASE_URL=sqlite:///:memory:
export ADMIN_USERNAME=test_admin
export ADMIN_PASSWORD=test_pass
export ADMIN_SECRET=test_secret
export KAFKA_ENABLED=false
export FEEDBACK_ENABLED=false
export USE_REDIS_STORAGE=false
uv run pytest tests/application/services/test_payment_service.py -v --no-cov
```

Не копировать рабочую `.env` в test checkout. Fixture get_config должен задавать все нужные внешние clients как fake; реальная сеть запрещена, кроме отдельной тестовой Postgres. `--no-cov` только для быстрых RED/GREEN, не способ обойти финальный coverage gate.

### 3.2. PostgreSQL без влияния на production

В Task02 создать **самостоятельный docker-compose.financial-test.yml** только с db_test, migrate_test и test, отдельным project name. Существующий docker-compose.test.yml нельзя запускать standalone: nginx в нём overlay без image/build, а app ссылается на .env. Main/dev overlay не подключать. Новый файл не содержит app/nginx, env_file, внешних credentials и не наследует production сервисы. Команды ниже — только после создания этого файла и fixtures Task02:

```bash
docker compose -p ugc-financial-test --env-file /dev/null -f docker-compose.financial-test.yml config --quiet
docker compose -p ugc-financial-test --env-file /dev/null -f docker-compose.financial-test.yml build test migrate_test
docker compose -p ugc-financial-test --env-file /dev/null -f docker-compose.financial-test.yml up -d --wait db_test
docker compose -p ugc-financial-test --env-file /dev/null -f docker-compose.financial-test.yml run --rm migrate_test
docker compose -p ugc-financial-test --env-file /dev/null -f docker-compose.financial-test.yml run --rm   -e DATABASE_URL=sqlite:///:memory:   -e FINANCIAL_TEST_DATABASE_URL=postgresql+psycopg://ugc:ugc@db_test:5432/ugc_test   -e BOT_TOKEN=test-token -e ADMIN_USERNAME=test_admin   -e ADMIN_PASSWORD=test_pass -e ADMIN_SECRET=test_secret   -e KAFKA_ENABLED=false -e FEEDBACK_ENABLED=false -e USE_REDIS_STORAGE=false   test python -m pytest tests/postgres_financial -v --no-cov   --require-financial-postgres --timeout=60
```

В каждой PG-карточке selector добавляется в последнюю команду (`<file> -k <selector>` вместо каталога). Изолированный Postgres не опубликован портом на host; нельзя без дополнительной сети подставлять db_test в host uv run.

PG-fixtures: отдельная настройка FINANCIAL_TEST_DATABASE_URL, test-database guard, real sessions, миграции, уборка только синтетических test IDs/test schema. Concurrency tests должны иметь ≥2 разных committed connections; FakeTM/SQLite не подходит. Увеличенный60s timeout только этому suite, без ослабления unit timeout5s. Не включать xdist до доказанной DB-изоляции. DB pools production не расширять; при PgBouncer session mode удерживать короткие транзакции и небольшой пул.

Важно для CI: default skip PG suite допустим только в локальном unit-only запуске без URL. Обязательный CI job устанавливает --require-financial-postgres; отсутствие сервера/env делает job failed, а не зелёный skip. Coverage98% считается полным прогоном с PG suite, а не усечённым набором.

### 3.3. Gate на границе каждого PR

```bash
make format-check lint typecheck
make coverage
# либо эквивалент make all в изолированном контуре с тестовым PG env
```

`make all` включает coverage98%. Существующий baseline97.41% — реальный blocker, не разрешение ослабить threshold или написать в описании «tests passed» вместо CI failure. PG migration suite и WebView E2E дополнительно не заменяются lint. Не использовать make migrate/docker-up/dev-up в production для тестирования.

## 4. Детальные задачи

Команды/expected results ниже описывают будущую проверку, а не выполненную. Имена новых test selectors — договорённый интерфейс плана, их предстоит создать. Для каждой карточки пройти весь микроцикл §3.1 отдельно по каждому указанному поведению.

### Task 01: Зафиксировать baseline и восстановить coverage без смены порога

**Пакет:** PR-00. **Зависимости:** нет. **Приёмка:** подготовительный gate, без отдельного AC.

**Files:**
- `Read: Makefile, pyproject.toml, .github/workflows/lint-test.yml`
- `Modify: только адресные tests/ для реально непокрытых ветвей после отчёта coverage`
- **Test target:** `tests/application/services/test_payment_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Сначала очистить унаследованные E2E_*/TELEGRAM_E2E_*/MAX_E2E_* по §3.1, затем выполнить полный baseline, сохранить исходные failures/skips/coverage.xml. Очистка обязательна уже здесь, до появления guard Task02: DATABASE_URL не обезвреживает E2E_DATABASE_URL cleanup. Для уже существующего поведения допустим passing characterization test; это не выдуманный RED. Для обнаруженного дефекта — отдельный воспроизводящий failing test.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
make all
```

**Step 3 — Минимальная реализация:** Адресно покрыть реально недостающие ветви исходного кода по coverage.xml; не менять бизнес-поведение, COV_FAIL=98, omit или pragma ради процента. Если 98% не достигнуты — PR-00 остаётся blocker, а не объявляется зелёным.

**Step 4 — GREEN / следующие маленькие циклы:** make all должен завершиться 0; сохранить фактические результаты, версии и commit. Название baseline — служебный ориентир, не новый тест: команда этой задачи make all, а не pytest -k baseline.

**Step 5 — Verification / review:** baseline зафиксирован; после адресного покрытия — exit0, coverage≥98%; никакой обещанной фиксированной прибавки процента. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 02: Изолированный PostgreSQL-контур и отказ подключения к неизвестной БД

**Пакет:** PR-00. **Зависимости:** 1. **Приёмка:** подготовительный gate, без отдельного AC.

**Files:**
- `Create: docker-compose.financial-test.yml`
- `Modify: tests/e2e/conftest.py (guard before any cleanup/sessionstart)`
- `Modify: tests/conftest.py (register pytest_addoption early for complete-suite CLI)`
- `Create: tests/postgres_financial/conftest.py`
- `Create: tests/postgres_financial/test_environment_guard.py`
- `Modify: .github/workflows/lint-test.yml`
- **Test target:** `tests/postgres_financial/test_environment_guard.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Передать отсутствующий URL, production-like database name и SQLite: fixture должна отказать, а не открыть соединение/пропустить обязательный job.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_environment_guard.py -k test_requires_explicit_test_database -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Добавить FINANCIAL_TEST_DATABASE_URL, guard тестового имени/host и явный режим --require-financial-postgres. Зарегистрировать pytest_addoption в корневом tests/conftest.py до CLI parse; nested conftest только читает option, иначе make coverage не распознает флаг. Отдельный каталог не наследует SQLite engine из tests/integration/conftest.py. Создать standalone compose из §3.2 и проверить config --quiet до build/up. В tests/e2e/conftest.py поставить deny-by-default guard ДО любого cleanup/DELETE/sessionstart: явный тестовый URL/marker и локальный synthetic app. Regression на чужой URL проверяет отказ до create_engine/соединения/DELETE. Guard нельзя откладывать до Task42. Добавить PostGIS service и migrations перед полным coverage в CI; на coverage step задать PYTEST_ADDOPTS=--require-financial-postgres и FINANCIAL_TEST_DATABASE_URL. Миграции получают DATABASE_URL=только_этот_тестовый_PG отдельным scoped env. Обязательный режим не допускает skip финансового PG-набора.

**Step 4 — GREEN / следующие маленькие циклы:** Два независимых sessions действительно видят committed данные; engine dispose проверен. Unit harness не перетирает окружение PG fixture; в CI запускается весь coverage с PG-набором, а не отдельный непокрываемый smoke.

**Step 5 — Verification / review:** поведенческий RED на исходной реализации; после minimal change GREEN на реальной PostgreSQL. Выполнять внутри test container по §3.2, не на host/production. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 03: Запретить чтение чужой пары менеджером того же заказа

**Пакет:** PR-01. **Зависимости:** 1. **Приёмка:** AC-01.

**Files:**
- `Modify: src/ugc_bot/application/services/manager_service.py`
- `Modify: src/ugc_bot/miniapp/api.py`
- `Modify: tests/unit/test_miniapp_manager_endpoints.py`
- **Test target:** `tests/unit/test_miniapp_manager_endpoints.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Менеджер состоит в order, но dispatch.manager_id принадлежит другому: detail обязан дать 403 до чтения контактов.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/unit/test_miniapp_manager_endpoints.py -k test_other_manager_cannot_read_creator -v --no-cov
```

**Step 3 — Минимальная реализация:** Выделить один application authorization метод проверки конкретного dispatch/assignment; отдельно admin capability. Не ограничиваться is_manager_for_order и не доверять user_id из body.

**Step 4 — GREEN / следующие маленькие циклы:** Своя пара разрешена; чужой order/creator, отсутствующий dispatch и невалидная идентичность отклонены. Проверить read path admin и отсутствие утечки контактов в ошибке.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 04: Проверять ту же пару во всех операционных действиях

**Пакет:** PR-01. **Зависимости:** 3. **Приёмка:** AC-01, AC-02.

**Files:**
- `Modify: src/ugc_bot/miniapp/api.py`
- `Modify: src/ugc_bot/application/services/interaction_service.py`
- `Modify: tests/unit/test_miniapp_manager_endpoints.py`
- **Test target:** `tests/unit/test_miniapp_manager_endpoints.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Параметризовать ugc-video/remove/feedback и stale assignment; отдельно feedback с blogger_id без dispatch: нельзя создать Interaction.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/unit/test_miniapp_manager_endpoints.py -k test_other_manager_cannot_mutate_creator -v --no-cov
```

**Step 3 — Минимальная реализация:** Переиспользовать authorization из задачи 3 до мутации и уведомлений. get_or_create не должен создавать связь на основании произвольного UUID. Проверить версию назначения повторно в write transaction.

**Step 4 — GREEN / следующие маленькие циклы:** Ни запись, ни сообщение не возникают при отказе; собственные операции сохраняют прежние ответы API. Не расширять доступ к общему резерву.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 05: Конфликт feedback не превращается в успех

**Пакет:** PR-02. **Зависимости:** 2,3. **Приёмка:** AC-03.

**Files:**
- `Create: src/ugc_bot/infrastructure/db/repositories/legacy_financial_guards.py`
- `Modify: src/ugc_bot/application/ports.py`
- `Modify: src/ugc_bot/container/service_factory.py`
- `Modify: src/ugc_bot/container/repository_factory.py`
- `Modify: src/ugc_bot/container/types.py`
- `Modify: src/ugc_bot/container/__init__.py`
- `Create: src/ugc_bot/application/services/legacy_financial_guard.py`
- `Modify: src/ugc_bot/infrastructure/db/models.py`
- `Create: src/ugc_bot/infrastructure/db/migrations/versions/<next_revision>_legacy_financial_safety_guard.py`
- `Modify: src/ugc_bot/bot/telegram/handlers/referral.py`
- `Modify: src/ugc_bot/bot/max/handlers/referral.py`
- `Modify: src/ugc_bot/admin/app.py (legacy payout guard)`
- `Create: tests/postgres_financial/test_legacy_dispute_payout_guard.py`
- `Modify: src/ugc_bot/application/services/interaction_service.py`
- `Modify: src/ugc_bot/bot/telegram/handlers/feedback.py`
- `Modify: src/ugc_bot/bot/max/handlers/feedback.py`
- `Modify: tests/application/services/test_interaction_service.py`
- **Test target:** `tests/application/services/test_interaction_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Реальный service flow success+no_deal должен дать ISSUE; отдельно issue+молчание сразу блокирует денежное продвижение, в том числе до окончания complaint FSM.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_interaction_service.py -k test_conflicting_feedback_opens_issue -v --no-cov
```

**Step 3 — Минимальная реализация:** Исправить приоритеты агрегирования и места, где service откладывает запись до второго ответа. Использовать текущий ISSUE для legacy, не добавлять все v1 состояния в legacy enum. Открыть/связать case по текущему механизму; старые начисления не переписывать.

**Step 4 — GREEN / следующие маленькие циклы:** Матрица обеих сторон и порядка ответов; OK+OK сохраняется. Stage A сам обязан блокировать legacy payout: создать durable wallet safety-guard recipient/currency и сохранить блокировку при ISSUE в той же transaction. Все текущие Telegram/MAX mark-paid/create и PayoutRequestAdmin проверяют этот guard под общей блокировкой; generic status/amount edit без проверки запрещён. Если legacy source нельзя надёжно выделить, fail-closed весь wallet с ручным review, не просто уведомление админа. Реальный PostgreSQL тест test_legacy_dispute_payout_guard.py подтверждает issue-vs-payout race. Дополнительная обязательная команда внутри test container §3.2: `python -m pytest tests/postgres_financial/test_legacy_dispute_payout_guard.py -k test_issue_blocks_payout_under_race -v --no-cov --require-financial-postgres --timeout=60`. Task37 расширяет этот уже работающий gate, а не впервые вводит защиту.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 06: False от retry не является успешной доставкой

**Пакет:** PR-02. **Зависимости:** 1. **Приёмка:** AC-04.

**Files:**
- `Modify: src/ugc_bot/feedback_scheduler.py`
- `Modify: tests/scheduler/test_feedback_scheduler.py`
- **Test target:** `tests/scheduler/test_feedback_scheduler.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** send_with_retry=False по всем каналам: функция должна вернуть False и не выполнить успешный scheduler advance.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/scheduler/test_feedback_scheduler.py -k test_failed_send_does_not_advance_schedule -v --no-cov
```

**Step 3 — Минимальная реализация:** Учесть фактический bool результата по каждому каналу, логировать failed отдельно; успех только при хотя бы одной достоверной принятой отправке в legacy. Никаких v1 72 часов на этом bool: они будут durable в задачах 27–31.

**Step 4 — GREEN / следующие маленькие циклы:** Нет target, все False, один accepted, исключение, blocked bot и смешанные каналы. Отправка отдельным каналам не должна автоматически доказывать получение другой стороной.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 07: После переназначения сообщать действующего менеджера

**Пакет:** PR-02. **Зависимости:** 3. **Приёмка:** AC-06.

**Files:**
- `Modify: src/ugc_bot/miniapp/api.py`
- `Modify: src/ugc_bot/application/services/manager_service.py`
- `Modify: tests/unit/test_miniapp_manager_endpoints.py`
- **Test target:** `tests/unit/test_miniapp_manager_endpoints.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Вернуть автора из резерва, назначить другого manager_id: контакт в отправке сейчас берётся из stale dispatch.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/unit/test_miniapp_manager_endpoints.py -k test_reserve_return_uses_current_manager -v --no-cov
```

**Step 3 — Минимальная реализация:** Использовать результат назначения/обновлённую запись, сохранённую в transaction; сетевой send после commit. Не менять исходный round-robin на новый алгоритм.

**Step 4 — GREEN / следующие маленькие циклы:** Назначение, response и уведомление согласованы; повтор действия не меняет assignment и не создаёт лишнего contact notification.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 08: Reconciliation различает двух авторов одного партнёра

**Пакет:** PR-03. **Зависимости:** 2. **Приёмка:** AC-05.

**Files:**
- `Modify: src/ugc_bot/infrastructure/db/repositories/referrals.py`
- `Create: tests/postgres_financial/test_referral_reconciliation.py`
- `Modify: tests/scheduler/test_referral_reconciliation_scheduler.py`
- **Test target:** `tests/postgres_financial/test_referral_reconciliation.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** В одном CLOSED+PAID order два OK автора одного referrer; income есть только у первого. Реальный SQL должен вернуть второго.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_referral_reconciliation.py -k test_second_creator_income_is_still_missing -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Добавить referred_user_id в корреляцию/outerjoin; сохранить разные income_type. Не менять формулу legacy ставки в этом bugfix.

**Step 4 — GREEN / следующие маленькие циклы:** Повторный reconciliation не дублирует строки; advertiser/creator и разные recipients независимы. Fake тест не заменяет SQL regression.

**Step 5 — Verification / review:** поведенческий RED на исходной реализации; после minimal change GREEN на реальной PostgreSQL. Выполнять внутри test container по §3.2, не на host/production. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 09: Согласовать unique constraints ORM и мигрированной схемы

**Пакет:** PR-03. **Зависимости:** 2,8. **Приёмка:** AC-07, AC-09.

**Files:**
- `Modify: src/ugc_bot/infrastructure/db/models.py`
- `Create: src/ugc_bot/infrastructure/db/migrations/versions/<next_revision>_financial_legacy_constraints.py`
- `Create: tests/postgres_financial/test_schema_parity.py`
- **Test target:** `tests/postgres_financial/test_schema_parity.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** После upgrade head сравнить constraints модели/inspector; проверить законные две строки для двух referred_users и отказ точному дублю.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_schema_parity.py -k test_income_constraints_match_migrations -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Использовать фактический Alembic head, не выдумывать номер; сохранить unique с referred_user. Для bindings добавить unique referred_user_id только после preflight duplicates report; при дублях остановиться, не удалять.

**Step 4 — GREEN / следующие маленькие циклы:** Create-from-metadata и migrations имеют одинаковые инварианты. Fresh upgrade и upgrade с синтетическими legacy данными. Для больших таблиц заранее выбрать online/concurrent index strategy, lock_timeout и восстановление после invalid index, по фактическому preflight объёму, не вслепую. Продакшен миграцию не запускать в рамках кодового теста.

**Step 5 — Verification / review:** поведенческий RED на исходной реализации; после minimal change GREEN на реальной PostgreSQL. Выполнять внутри test container по §3.2, не на host/production. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 10: Повтор capture и гонка referral binding

**Пакет:** PR-03. **Зависимости:** 2,9. **Приёмка:** AC-08, AC-09.

**Files:**
- `Modify: src/ugc_bot/application/services/payment_service.py`
- `Modify: src/ugc_bot/application/services/referral_service.py`
- `Modify: src/ugc_bot/infrastructure/db/repositories/referrals.py`
- `Modify: tests/application/services/test_payment_service.py`
- `Create: tests/postgres_financial/test_legacy_races.py`
- **Test target:** `tests/postgres_financial/test_legacy_races.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** После первого PAID и смены order.status повтор payment event обязан вернуть прежний результат. Две конкурирующие регистрационные binding одного пользователя оставляют одну активную связь.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_legacy_races.py -k test_capture_or_binding_races -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Сначала проверить ownership/идентичность внешнего платежа, затем повтор уже PAID, только после этого валидировать NEW для первой оплаты. В binding использовать DB unique и обработку конфликта, а не только read-then-write.

**Step 4 — GREEN / следующие маленькие циклы:** Несовпадающий payload того же external id отклонён; чужой advertiser не получает payment; гонка разрешается в DB, а не FakeTM.

**Step 5 — Verification / review:** поведенческий RED на исходной реализации; после minimal change GREEN на реальной PostgreSQL. Выполнять внутри test container по §3.2, не на host/production. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 11: Minor units, отдельная чистая v1 математика и calendar year

**Пакет:** PR-04. **Зависимости:** 1. **Приёмка:** AC-10, AC-13, AC-14, AC-15, AC-35.

**Files:**
- `Create: src/ugc_bot/domain/financial.py`
- `Create: tests/application/services/test_financial_math.py`
- `Read-only: src/ugc_bot/application/services/referral_commission.py`
- **Test target:** `tests/application/services/test_financial_math.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Параметризовать int minor sums, HALF_UP, год до/на годовщине, 29 февраля→28 февраля, negative/unknown currency rejection.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_financial_math.py -k test_financial_math_boundaries -v --no-cov
```

**Step 3 — Минимальная реализация:** Создать чистые v1 функции first_anniversary, commission_minor, rate_bps. Не менять resolve_rate legacy и float-поля старых Payment сразу; адаптация в задачи 16/26.

**Step 4 — GREEN / следующие маленькие циклы:** Нет float внутри v1 функций; 0/99/100/199/200/399/400 и 3% со второй годовщины; воспроизводимое rounding полного refund.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 12: Policy defaults false, обязательные параметры и disabled overrides

**Пакет:** PR-04. **Зависимости:** 11. **Приёмка:** AC-15, AC-43, AC-44, AC-51.

**Files:**
- `Modify: config/env.example`
- `Modify: src/ugc_bot/config.py`
- `Create: src/ugc_bot/application/services/financial_policy_service.py`
- `Create: tests/application/services/test_financial_policy_service.py`
- **Test target:** `tests/application/services/test_financial_policy_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Включение v1 без refund_window/selection deadline/approved policy запрещено; feature flags по умолчанию false; новый override и нестандартная цена отклонены.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_financial_policy_service.py -k test_policy_fails_closed -v --no-cov
```

**Step 3 — Минимальная реализация:** Добавить FinancialConfig в действующие flat-key mappings и вложенный config, typed policy и validate_for_capture. selection_due_at принадлежит конкретному order, а не глобальному default. Принятие решений не подменяет наличие документов/параметров.

**Step 4 — GREEN / следующие маленькие циклы:** D-01–D-10 не re-open; заполненный разрешённый policy допускает allowlisted новый order; старый не переключается при включении flag.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 13: Зафиксировать ledger ADR и порядок блокировок

**Пакет:** PR-04. **Зависимости:** 5,11,12. **Приёмка:** AC-28, AC-35, AC-50.

**Files:**
- `Create: docs/superpowers/specs/2026-10-22-financial-ledger-adr.md`
- `Create: src/ugc_bot/application/financial_ports.py`
- `Create: tests/application/services/test_financial_contracts.py`
- **Test target:** `tests/application/services/test_financial_contracts.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Контракт отклоняет сумму без currency, bucket transfer без source/destination, reservation без request/allocation и correction без исходного основания.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_financial_contracts.py -k test_journal_contract_rejects_ambiguous_movement -v --no-cov
```

**Step 3 — Минимальная реализация:** Один журнал immutable economic/transfer events; положительные amounts, типизированные issuance/reversal/recovery. Определить capabilities TransactionManager/Clock/repositories. Общая координационная wallet-row на recipient+currency; порядок locks: wallets sorted → items sorted → obligations sorted → payout requests; после locks повторно validate expected versions.

**Step 4 — GREEN / следующие маленькие циклы:** В ADR формула G−V−F+R=U−D, payload-hash/idempotence, historical paid и debt раздельны; без общих блокировок across legacy/v1 payout запрещён. Порты не импортируют SQLAlchemy.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 14: Expand migrations: policy, items, assignments и payment allocations

**Пакет:** PR-05. **Зависимости:** 2,12,13. **Приёмка:** AC-07, AC-10, AC-42.

**Files:**
- `Modify: tests/integration/conftest.py (only dialect-specific schema compatibility if needed)`
- `Modify: src/ugc_bot/infrastructure/db/models.py`
- `Create: src/ugc_bot/infrastructure/db/repositories/financial_items.py`
- `Create: src/ugc_bot/infrastructure/db/migrations/versions/<next_revision>_financial_items.py`
- `Create: tests/postgres_financial/test_financial_items_schema.py`
- **Test target:** `tests/postgres_financial/test_financial_items_schema.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Fresh upgrade, nullable legacy bridge, unique(order_id,ordinal), one current assignment и payment-component allocation FK/checks.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_financial_items_schema.py -k test_financial_items_schema -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Добавить таблицы, minor units BIGINT, timezone-aware timestamps и policy_version. Не удалять старые поля orders/payments; FK allocation и сверка захваченной суммы обязательны. Все методы принимают caller session.

**Step 4 — GREEN / следующие маленькие циклы:** Legacy seed читабелен после upgrade; concurrent assignments не дают двух текущих; Alembic revisions именуются после реального head. Никаких автоматических исторических backfill сумм.

**Step 5 — Verification / review:** поведенческий RED на исходной реализации; после minimal change GREEN на реальной PostgreSQL. Выполнять внутри test container по §3.2, не на host/production. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 15: Создание оплачиваемых позиций и выбор сопровождения до оплаты

**Пакет:** PR-05. **Зависимости:** 12,14. **Приёмка:** AC-10, AC-12, AC-41, AC-51.

**Files:**
- `Create: src/ugc_bot/application/services/paid_item_service.py`
- `Modify: src/ugc_bot/application/services/order_service.py`
- `Create: tests/application/services/test_paid_item_service.py`
- **Test target:** `tests/application/services/test_paid_item_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Создать 30 selection items, включить сопровождение для выбранных; изменить тариф после сохранения quote — существующая оплаченная цена не меняется.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_paid_item_service.py -k test_selection_and_accompaniment_components -v --no-cov
```

**Step 3 — Минимальная реализация:** Зафиксировать amounts per item, выбор услуги, контакты и selection_due_at до capture. После capture изменение только отдельной command/change-order, не перезапись старого price.

**Step 4 — GREEN / следующие маленькие циклы:** Стандартный 50000+120000 RUB; seller fee и referral bases различаются; повтор service-selection idempotent. Валюта без опубликованного стандартного тарифа v1 отклоняется/остаётся в разрешённом legacy пути, не получает молчаливый FX или выдуманную цену. Не отправлять lead до commit.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 16: Capture v1: доверенный платёж и атомарные allocations

**Пакет:** PR-05. **Зависимости:** 10,15. **Приёмка:** AC-08, AC-10, AC-12, AC-27.

**Files:**
- `Modify: src/ugc_bot/admin/app.py (PaymentAdmin write guard for v1)`
- `Modify: src/ugc_bot/application/services/payment_service.py`
- `Modify: src/ugc_bot/bot/telegram/handlers/payments.py`
- `Modify: tests/application/services/test_payment_service.py`
- `Create: tests/postgres_financial/test_v1_capture.py`
- **Test target:** `tests/postgres_financial/test_v1_capture.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Неверные amount/currency/owner/signature, duplicate external id и crash между allocations не оставляют частично PAID items.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_v1_capture.py -k test_v1_capture_allocations_are_atomic -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Добавить version-aware path; внешний capture → payment+allocations+item paid+snapshot request/outbox в одной transaction. captured_at — достоверный timestamp payment protocol/первого durable capture, не datetime.now при позднем worker или retry; mapping поля подтверждается по реальному adapter payload отдельным contract test, неизвестное время не выдумывается. Не использовать current tariff или payment total/N для v1 комиссии. Legacy behavior routing неизменен.

**Step 4 — GREEN / следующие маленькие циклы:** Дубликат после order-status change возвращает прежний результат; refunded/unpaid value не даёт новых allocations. SQLAdmin PaymentAdmin не меняет v1 amount/currency/status напрямую в обход capture/ledger; отдельный regression на edit/create. Неизвестные out-of-order refunds сохраняются в inbox задачи 26 и разрешаются связанной refund command задач 35/40.

**Step 5 — Verification / review:** поведенческий RED на исходной реализации; после minimal change GREEN на реальной PostgreSQL. Выполнять внутри test container по §3.2, не на host/production. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 17: Оплаченное назначение, item identity и round-robin

**Пакет:** PR-05. **Зависимости:** 14,16. **Приёмка:** AC-10, AC-15, AC-38.

**Files:**
- `Modify: src/ugc_bot/application/services/offer_response_service.py`
- `Modify: src/ugc_bot/application/services/manager_service.py`
- `Modify: src/ugc_bot/infrastructure/db/repositories/orders.py`
- `Create: tests/application/services/test_paid_item_assignment.py`
- **Test target:** `tests/application/services/test_paid_item_assignment.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Принятый отклик выделяет одну оплаченную позицию, не более одной на автора данного standard order; assignment до capture не создаёт денежного snapshot.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_paid_item_assignment.py -k test_assignment_keeps_paid_item_identity -v --no-cov
```

**Step 3 — Минимальная реализация:** Переиспользовать row lock order и round-robin; сохранить item_id/assignment version/manager_id. Событие назначения после capture с effective_at=max(assigned_at,captured_at); отменённое ранее назначение не получает доход.

**Step 4 — GREEN / следующие маленькие циклы:** В двух параллельных accept одна позиция не занята дважды; первичное назначение не доказывает исполнение подбора или успех автора.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 18: Expand ledger storage и append-only DB permissions

**Пакет:** PR-06. **Зависимости:** 13,14. **Приёмка:** AC-16, AC-27, AC-28, AC-50.

**Files:**
- `Read: docs/superpowers/specs/2026-10-22-financial-ledger-adr.md`
- `Modify: src/ugc_bot/infrastructure/db/models.py`
- `Create: src/ugc_bot/infrastructure/db/repositories/financial_ledger.py`
- `Create: src/ugc_bot/infrastructure/db/migrations/versions/<next_revision>_financial_ledger.py`
- `Create: tests/postgres_financial/test_financial_ledger_schema.py`
- **Test target:** `tests/postgres_financial/test_financial_ledger_schema.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Точный повтор business_key/operation_key конфликтует; два разных income kinds того же recipient разрешены; UPDATE/DELETE journal ограничены runtime ролью.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_financial_ledger_schema.py -k test_ledger_is_append_only -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Добавить obligations, movements, rate snapshots, financial_audit_events и wallet projection; координационная safety-row Task05 уже существует и переиспользуется. Append-only enforce trigger/DB permissions для рабочей роли, не только Python API; owner/migration role остаётся отдельной. Migration credentials не выдавать приложению.

**Step 4 — GREEN / следующие маленькие циклы:** Для constraint/permission tests использовать отдельную non-owner test role: superuser не доказывает запрет. Идемпотентные operation IDs и refs разрешают несколько различных корректировок.

**Step 5 — Verification / review:** поведенческий RED на исходной реализации; после minimal change GREEN на реальной PostgreSQL. Выполнять внутри test container по §3.2, не на host/production. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 19: Создать одно финансовое основание и проверить payload conflict

**Пакет:** PR-06. **Зависимости:** 18. **Приёмка:** AC-16, AC-27, AC-28.

**Files:**
- `Create: src/ugc_bot/application/services/financial_ledger_service.py`
- `Create: tests/application/services/test_financial_ledger_service.py`
- **Test target:** `tests/application/services/test_financial_ledger_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Один event с client/creator одной личности даёт две обязанности; повтор даёт прежние результаты; тот же key с другим payload отклонён.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_financial_ledger_service.py -k test_issue_is_idempotent_by_business_key -v --no-cov
```

**Step 3 — Минимальная реализация:** Реализовать issue/potential_basis, operation hash и projection update в caller transaction. Без известного автора/партнёра/рассчитанной политики денежной записи нет. Отсутствующий партнёр после проверки — no obligation, не amount=0.

**Step 4 — GREEN / следующие маленькие циклы:** Recorded/effective timestamps раздельны; дедупликация по event не съедает второе законное основание.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 20: Переносы buckets, hold release и dispute block

**Пакет:** PR-06. **Зависимости:** 19. **Приёмка:** AC-23, AC-26, AC-28, AC-35, AC-36.

**Files:**
- `Modify: src/ugc_bot/application/services/financial_ledger_service.py`
- `Modify: src/ugc_bot/infrastructure/db/repositories/financial_ledger.py`
- `Modify: tests/application/services/test_financial_ledger_service.py`
- **Test target:** `tests/application/services/test_financial_ledger_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** pending→hold→available переносит ту же сумму, не создаёт новый доход; blocked/unknown policy не release; частичный cancellation не уходит ниже нуля.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_financial_ledger_service.py -k test_bucket_transfer_preserves_liability -v --no-cov
```

**Step 3 — Минимальная реализация:** Реализовать typed transfers с общей wallet/item lock strategy. Available_at хранить, а не выводить из текущего config. Replay должен считать transfers без двойного суммирования.

**Step 4 — GREEN / следующие маленькие циклы:** Concurrency release-hold против dispute повторить PostgreSQL-тестом после задачи 34; до этого monetary write flags off.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 21: Replay воспроизводит суммы, резервы и контрольное равенство

**Пакет:** PR-06. **Зависимости:** 20. **Приёмка:** AC-28, AC-36, AC-50.

**Files:**
- `Create: src/ugc_bot/application/services/financial_reconciliation_service.py`
- `Create: tests/application/services/test_financial_reconciliation_service.py`
- **Test target:** `tests/application/services/test_financial_reconciliation_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Испортить projection отдельно от immutable journal: сверка ловит mismatch; корректный journal с refund после paid и recovery восстанавливает debt и U.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_financial_reconciliation_service.py -k test_replay_rebuilds_allocation_and_balance -v --no-cov
```

**Step 3 — Минимальная реализация:** Вычислять G/V/F/R/U/D отдельно по recipient/currency, применять request/allocation refs и block/unblock events. Не делать max(balance,0). Repair только dry-run report, никакого автоматического UPDATE денежных строк.

**Step 4 — GREEN / следующие маленькие циклы:** Равенство и восстановление связей проверяются независимо, а не сравнением двух одинаково ошибочных totals. Mismatch ставит payout safety gate.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 22: Verified-count и исторические события грейда

**Пакет:** PR-07. **Зависимости:** 11,14. **Приёмка:** AC-14, AC-15, AC-46.

**Files:**
- `Modify: src/ugc_bot/infrastructure/db/models.py`
- `Create: src/ugc_bot/infrastructure/db/migrations/versions/<next_revision>_financial_grade_history.py`
- `Create: src/ugc_bot/application/services/referral_grade_service.py`
- `Modify: src/ugc_bot/application/services/instagram_verification_service.py`
- `Create: src/ugc_bot/infrastructure/db/repositories/financial_rates.py`
- `Create: tests/application/services/test_referral_grade_service.py`
- **Test target:** `tests/application/services/test_referral_grade_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** 99/100/199/200/399/400 проверенных invited creators; дубли соцсетей/связанных мессенджеров не повышают грейд.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_referral_grade_service.py -k test_verified_count_uses_unique_instagram_identity -v --no-cov
```

**Step 3 — Минимальная реализация:** Учитывать verified Instagram identity, canonical creator и первую binding; хранить effective_at события verification/revoke/merge. Первая начальная snapshot count из сверенного cutover; не сочинять history до него.

**Step 4 — GREEN / следующие маленькие циклы:** Снятие verified понижает только будущие snapshots; старые неизменны. Identity conflicts идут в review, не автоматическое объединение двух физических лиц.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 23: Снимки client при capture и creator при оплаченном назначении

**Пакет:** PR-07. **Зависимости:** 16,17,19,22. **Приёмка:** AC-12, AC-13, AC-14, AC-15, AC-16, AC-43.

**Files:**
- `Create: src/ugc_bot/application/services/rate_snapshot_service.py`
- `Modify: src/ugc_bot/application/services/referral_income_recorder.py`
- `Create: tests/application/services/test_rate_snapshot_service.py`
- **Test target:** `tests/application/services/test_rate_snapshot_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Платёж до появления автора; новый автор зарегистрирован после capture; изменение грейда до/после назначения; replacement в другой календарный период.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_rate_snapshot_service.py -k test_client_and_creator_use_different_snapshot_times -v --no-cov
```

**Step 3 — Минимальная реализация:** Client as-of capture, creator as-of max(active assignment time,capture time). История grade/binding/created_at читается на effective timestamp, не на время позднего worker. Legacy recorder не применяется к v1 orders; стандартные bps, overrides disabled.

**Step 4 — GREEN / следующие маленькие циклы:** Возраст считается по referred user; 29 февраля и boundary covered. Неизвестная история/конфликт — pending review, не guessed 3% или 0.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 24: Версионированная замена с актуальной невозвращённой базой

**Пакет:** PR-07. **Зависимости:** 17,20,23. **Приёмка:** AC-17, AC-38, AC-47.

**Files:**
- `Create: src/ugc_bot/application/services/item_replacement_service.py`
- `Create: tests/application/services/test_item_replacement_service.py`
- `Create: tests/postgres_financial/test_item_replacement_atomicity.py`
- **Test target:** `tests/postgres_financial/test_item_replacement_atomicity.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Частичный selection refund, затем замена, затем успех: новая комиссия с остатка; клиентская не повторяется, прежняя potential/obligation не остаётся активной.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_item_replacement_atomicity.py -k test_refund_then_replacement_uses_remaining_base -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Один item lock и transaction для отмены старого ожидающего основания, новой assignment и нового snapshot. Объективная причина, admin, floor limit; completed work — dispute path, не replacement.

**Step 4 — GREEN / следующие маленькие циклы:** Два concurrent replacement и exhausted quota; rollback всей команды при ошибке новой snapshot. Payment allocation повторно не создаётся.

**Step 5 — Verification / review:** поведенческий RED на исходной реализации; после minimal change GREEN на реальной PostgreSQL. Выполнять внутри test container по §3.2, не на host/production. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 25: Типизированные financial outbox events и routing без порчи order.activated

**Пакет:** PR-08. **Зависимости:** 13,18. **Приёмка:** AC-19, AC-27, AC-34, AC-43.

**Files:**
- `Modify: src/ugc_bot/application/services/outbox_publisher.py`
- `Modify: src/ugc_bot/outbox_processor.py`
- `Create: src/ugc_bot/application/services/financial_event_router.py`
- `Create: tests/application/services/test_financial_event_router.py`
- `Modify: src/ugc_bot/container/service_factory.py`
- **Test target:** `tests/application/services/test_financial_event_router.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Событие financial.v1.* нельзя отправить как order.activated существующим OrderActivationPublisher; неизвестный тип не отмечается processed как будто успешен.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_financial_event_router.py -k test_financial_event_never_activates_order -v --no-cov
```

**Step 3 — Минимальная реализация:** Добавить financial writer в тот же transaction и явный router/adapters. Сохранить legacy конструкторы/маршрут order.activated. Producer flags остаются off, пока consumer routing и его readiness не доказаны. Claim/filter не допускает двух разных processors без разделения типов.

**Step 4 — GREEN / следующие маленькие циклы:** Crash после commit до publish приводит к retry без новых денег; unsupported event → наблюдаемая retry/dead-letter. Не обещать external exactly-once.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 26: Durable inbox: порядок событий и конфликт payload

**Пакет:** PR-08. **Зависимости:** 19,25. **Приёмка:** AC-27, AC-29, AC-34.

**Files:**
- `Modify: src/ugc_bot/infrastructure/db/models.py`
- `Create: src/ugc_bot/infrastructure/db/migrations/versions/<next_revision>_financial_inbox.py`
- `Create: src/ugc_bot/application/services/financial_event_inbox_service.py`
- `Create: src/ugc_bot/infrastructure/db/repositories/financial_events.py`
- `Create: tests/postgres_financial/test_financial_event_inbox.py`
- **Test target:** `tests/postgres_financial/test_financial_event_inbox.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Два workers принимают один producer/event_id; иной payload того же ID — incident; refund до capture сохраняется, не теряется.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_financial_event_inbox.py -k test_duplicate_or_reordered_events_are_safe -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Сохранить received_at, payload hash и state; обработка финсобытия атомарна с ledger. Unknown reference → awaiting_dependency+safety flag; повтор после появления dependency не дублирует effects.

**Step 4 — GREEN / следующие маленькие циклы:** Повторный ingress не меняет исходное received_at. Зависшие события попадают в очередь исключений; невозможный порядок не приводит к auto-success.

**Step 5 — Verification / review:** поведенческий RED, затем GREEN на реальном PostgreSQL внутри test container §3.2 с FINANCIAL_TEST_DATABASE_URL и двумя независимыми sessions. Skip при отсутствии PG не считается успехом; required-mode обязателен. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 27: Delivery accepted/failed/unknown и фиксация доказательства передачи

**Пакет:** PR-08. **Зависимости:** 25,26. **Приёмка:** AC-04, AC-19, AC-24, AC-34.

**Files:**
- `Modify: src/ugc_bot/infrastructure/db/models.py`
- `Create: src/ugc_bot/infrastructure/db/migrations/versions/<next_revision>_financial_deliveries.py`
- `Create: src/ugc_bot/application/services/notification_delivery_service.py`
- `Create: tests/application/services/test_notification_delivery_service.py`
- `Create: src/ugc_bot/infrastructure/db/repositories/notification_deliveries.py`
- **Test target:** `tests/application/services/test_notification_delivery_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Accepted с message_id, False, exception и unknown-after-send; рестарт worker до записи ответа не должен трактовать unknown как успех.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_notification_delivery_service.py -k test_delivery_state_uses_actual_provider_result -v --no-cov
```

**Step 3 — Минимальная реализация:** Сеть вне DB lock; request/delivery states в коротких transactions. Сохранять provider refs, attempts, accepted_at либо recovery_confirmed_at, канал и назначение. Ретраи не создают новый business notification.

**Step 4 — GREEN / следующие маленькие циклы:** Первая достоверная accepted передача selection даёт fulfilment timestamp; API принятие не объявлять прочтением. Не превращать транспортные ретраи в финсобытия.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 28: Fulfilment selection и независимая клиентская комиссия по item

**Пакет:** PR-09. **Зависимости:** 16,20,23,27. **Приёмка:** AC-11, AC-12, AC-23, AC-51.

**Files:**
- `Create: src/ugc_bot/application/services/selection_fulfillment_service.py`
- `Create: tests/application/services/test_selection_fulfillment_service.py`
- **Test target:** `tests/application/services/test_selection_fulfillment_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** 30 оплачено, 25 передано, 5 refund: база/клиентская комиссия как AC-11; исходный order.CLOSED не заменяет accepted delivery.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_selection_fulfillment_service.py -k test_partial_delivery_releases_only_eligible_items -v --no-cov
```

**Step 3 — Минимальная реализация:** На принятую доставку фиксировать item.fulfilled и refund_window_end=accepted_at+policy duration, available_at=end+14d; остаётся hold до даты. Непереданные — без available, deadline extension с consent.

**Step 4 — GREEN / следующие маленькие циклы:** Возврат и dispute блокируют release только соответствующего основания/области case; новые тарифы не меняют snapshot старой позиции.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 29: Collaboration schema и допустимые команды claim

**Пакет:** PR-09. **Зависимости:** 14,17,19,26. **Приёмка:** AC-18, AC-25, AC-38.

**Files:**
- `Create: src/ugc_bot/application/evidence_ports.py`
- `Create: src/ugc_bot/application/services/evidence_service.py`
- `Create: src/ugc_bot/infrastructure/evidence_store.py`
- `Create: src/ugc_bot/infrastructure/db/repositories/financial_evidence.py`
- `Create: tests/application/services/test_evidence_service.py`
- `Modify: src/ugc_bot/infrastructure/db/models.py`
- `Create: src/ugc_bot/infrastructure/db/migrations/versions/<next_revision>_financial_collaborations.py`
- `Create: src/ugc_bot/domain/collaboration.py`
- `Create: src/ugc_bot/application/services/collaboration_service.py`
- `Create: src/ugc_bot/infrastructure/db/repositories/collaborations.py`
- `Create: tests/application/services/test_collaboration_service.py`
- **Test target:** `tests/application/services/test_collaboration_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Claim без evidence, чужим actor, неверной assignment/brief version или самим менеджером для своей выплаты отклонён.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_collaboration_service.py -k test_claim_requires_actor_evidence_and_matching_version -v --no-cov
```

**Step 3 — Минимальная реализация:** Раздельная state machine assigned/in_progress/success_claimed/delivery_blocked/delivery_unknown/success_final/disputed/expired. evidence_ref, due_at, expected_version. Добавить EvidenceStore/Resolver port и evidence_service: protected asset metadata/ownership, ACL, configurable size/MIME limits, безопасный storage adapter и audit read/write через financial_audit_events. Backend/retention/size policy выбираются явно до upload enable; missing configuration fail-closed. Произвольный URL не скачивать сервером; Telegram file_id разрешается только trusted provider adapter. Менеджер может приложить материал, но не сделать self approval.

**Step 4 — GREEN / следующие маленькие циклы:** UGC без размещения и публикация имеют разные evidence types. До claim нет publication=true, активный спор блокирует переход. Добавить отдельные tests на ACL protected evidence, type/size limits, запрет произвольного server-side fetch (SSRF). Telegram file_id хранить как provider identifier, не считать локальным файлом или уже загруженной картинкой.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 30: Запуск 72 часов только после достоверной доставки

**Пакет:** PR-09. **Зависимости:** 27,29. **Приёмка:** AC-19, AC-23, AC-24.

**Files:**
- `Modify: src/ugc_bot/application/services/collaboration_service.py`
- `Modify: src/ugc_bot/application/services/notification_delivery_service.py`
- `Modify: tests/application/services/test_collaboration_service.py`
- **Test target:** `tests/application/services/test_collaboration_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Claim в t0, failed send, accepted recovery в t1: deadline=t1+72h; unknown не запускает timer. Дубликаты не перезапускают существующий window.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_collaboration_service.py -k test_objection_window_starts_after_confirmed_delivery -v --no-cov
```

**Step 3 — Минимальная реализация:** Сохранить objection_started/deadline на первой достоверной acceptance; после unknown recovery впервые использовать recovery timestamp без backdating. Explicit authenticated confirm другой стороны разрешён даже blocked/unknown, если evidence/version совпали.

**Step 4 — GREEN / следующие маленькие циклы:** Явное подтверждение не подделывает accepted_at; no_objection и explicit имеют разные basis. UTC-boundary received_at <= deadline.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 31: Возражения, safety-stop и обработка очереди на границе срока

**Пакет:** PR-09. **Зависимости:** 20,26,30. **Приёмка:** AC-03, AC-20, AC-26.

**Files:**
- `Create: src/ugc_bot/infrastructure/db/repositories/financial_cases.py`
- `Modify: src/ugc_bot/infrastructure/db/models.py`
- `Create: src/ugc_bot/infrastructure/db/migrations/versions/<next_revision>_financial_cases.py`
- `Create: src/ugc_bot/application/services/financial_dispute_service.py`
- `Modify: src/ugc_bot/application/services/collaboration_service.py`
- `Create: tests/postgres_financial/test_objection_finalize_race.py`
- **Test target:** `tests/postgres_financial/test_objection_finalize_race.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Возражение получено на 71-м часу/ровно deadline, worker обработал позже finalize: право не теряется, funds не release. Два finalizers безопасны.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_objection_finalize_race.py -k test_timely_ingress_wins_over_late_worker -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Durable ingress received_at до ack; одна lock/version strategy с finalize/release и check необработанных timely events. Немедленный safety flag при нажатии проблемы, не ждать complaint FSM completion.

**Step 4 — GREEN / следующие маленькие циклы:** Проверить порядки commit обоих workers, не только asyncio.gather на fake. Late objection → manual case, не исчезновение и не обратный auto-debit.

**Step 5 — Verification / review:** поведенческий RED на исходной реализации; после minimal change GREEN на реальной PostgreSQL. Выполнять внутри test container по §3.2, не на host/production. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 32: Expiry, deadline extension и завершение без публикационного вымысла

**Пакет:** PR-09. **Зависимости:** 29,30,31. **Приёмка:** AC-21, AC-22, AC-23, AC-25.

**Files:**
- `Create: src/ugc_bot/financial_scheduler.py`
- `Modify: src/ugc_bot/application/services/collaboration_service.py`
- `Modify: tests/application/services/test_collaboration_service.py`
- **Test target:** `tests/application/services/test_collaboration_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Обе стороны молчат до due+14d → expired; claim до cutoff сохраняет полное окно за пределами expiry. Extension не сбрасывает active claim.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_collaboration_service.py -k test_expiry_does_not_interrupt_timely_claim -v --no-cov
```

**Step 3 — Минимальная реализация:** Injected Clock, versioned due_at/consent, locked scheduler claim. Фиксировать confirmation_basis и evidence отдельно; no_objection не делает published=true. Поздние материалы → review_pending.

**Step 4 — GREEN / следующие маленькие циклы:** Граница до/на/после expiry; recovery после outage; тексты сообщают реальный статус. Никаких sleep на сутки и влияния legacy postpone-four-times.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 33: Hold release автора и очереди споров

**Пакет:** PR-09. **Зависимости:** 20,23,31,32. **Приёмка:** AC-20, AC-23, AC-26, AC-27.

**Files:**
- `Modify: src/ugc_bot/financial_scheduler.py`
- `Modify: src/ugc_bot/application/services/financial_ledger_service.py`
- `Modify: src/ugc_bot/application/services/financial_dispute_service.py`
- `Create: tests/postgres_financial/test_hold_release_race.py`
- **Test target:** `tests/postgres_financial/test_hold_release_race.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** success_final даёт hold14d, не available; поздний issue до release, два release-workers и outstanding timely inbox исключают выпуск денег.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_hold_release_race.py -k test_dispute_prevents_release_after_success -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Создать author obligation по snapshot и release только при отсутствии blocking cases/refunds/unknown; целевой available_at неизменен. При reopened success — audit/corrective events, не перепись original.

**Step 4 — GREEN / следующие маленькие циклы:** Legacy feedback scheduler исключает v1 assignments; Issue и все frontend пути используют те же services.

**Step 5 — Verification / review:** поведенческий RED на исходной реализации; после minimal change GREEN на реальной PostgreSQL. Выполнять внутри test container по §3.2, не на host/production. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 34: Management entitlement на оплаченные 1200 и заработанные 600

**Пакет:** PR-10. **Зависимости:** 15,17,19,29,33. **Приёмка:** AC-16, AC-37, AC-38, AC-41.

**Files:**
- `Modify: src/ugc_bot/infrastructure/db/repositories/financial_items.py`
- `Modify: src/ugc_bot/infrastructure/db/models.py`
- `Create: src/ugc_bot/infrastructure/db/migrations/versions/<next_revision>_management_entitlements.py`
- `Create: src/ugc_bot/application/services/management_income_service.py`
- `Create: tests/application/services/test_management_income_service.py`
- `Modify: src/ugc_bot/application/services/manager_service.py`
- **Test target:** `tests/application/services/test_management_income_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** 30 сопровождений, 20 успешных: только20×600 gross; внутренний бесплатный менеджер не получает 600. Один user может получить также client/creator referral.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_management_income_service.py -k test_only_successful_paid_management_earns_600 -v --no-cov
```

**Step 3 — Минимальная реализация:** Отдельное management основание на item/entitlement, оплаченный accompaniment component и действующий получатель. При success_final hold14d, передача до успеха versioned+reason; после — case, не подмена recipient.

**Step 4 — GREEN / следующие маленькие циклы:** Нет автоматического split/процента готовности; одновременно claim и handover ведут в review; уже заработанное не переходит manager_id на момент payout.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 35: Компонентные возвраты до выплаты и compensating entries

**Пакет:** PR-11. **Зависимости:** 20,24,26,28,34. **Приёмка:** AC-12, AC-29, AC-30, AC-35, AC-47.

**Files:**
- `Modify: src/ugc_bot/infrastructure/db/models.py`
- `Create: src/ugc_bot/infrastructure/db/migrations/versions/<next_revision>_financial_refunds.py`
- `Create: src/ugc_bot/application/services/refund_service.py`
- `Create: tests/application/services/test_refund_service.py`
- `Create: src/ugc_bot/infrastructure/db/repositories/financial_refunds.py`
- **Test target:** `tests/application/services/test_refund_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Refund selection/management по отдельности на pending/hold/available; полный после нескольких частичных не оставляет rounding dust и не отменяет больше базы.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_refund_service.py -k test_component_refund_creates_linked_correction -v --no-cov
```

**Step 3 — Минимальная реализация:** Валидация capture allocation, cumulative refund ceiling, status requested/processing/succeeded/unknown. Денежную correction создавать по подтверждённому факту; при запросе risk freeze. management перерасчёт по мотивированному entitlement решению, не автоматическая пропорция.

**Step 4 — GREEN / следующие маленькие циклы:** При selection refund обе referral sides используют frozen rates; delta correction = target_commission(previous_remaining_base) − target_commission(new_remaining_base), оба target считаются выбранным HALF_UP. Не округлять каждый кусок refund независимо: полный возврат должен обнулить obligation без dust. Accompaniment не трогает selection. Повтор refund_id не дублирует reversal.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 36: Возврат/поздний спор после paid сохраняет долг и историю

**Пакет:** PR-11. **Зависимости:** 21,31,35. **Приёмка:** AC-26, AC-30, AC-50.

**Files:**
- `Modify: src/ugc_bot/application/services/refund_service.py`
- `Modify: src/ugc_bot/application/services/financial_dispute_service.py`
- `Modify: tests/application/services/test_refund_service.py`
- **Test target:** `tests/application/services/test_refund_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Подтверждённый возврат основания после paid: выплата остаётся, debt виден отдельно, нет скрытого вычитания из нового несвязанного дохода.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_refund_service.py -k test_refund_after_paid_creates_debt_case -v --no-cov
```

**Step 3 — Минимальная реализация:** Linked cancellation экономического основания + case/debt; recovery только подтверждённым возвратом получателя и отдельной операцией. Не выдавать debt за отрицательный available.

**Step 4 — GREEN / следующие маленькие циклы:** G−V−F+R=U−D при full/partial refund, debt recovery и новых доходах. Late issue сам по себе freeze/review, не признанная экономическая отмена без решения.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 37: Единый legacy/v1 payout gate до любых новых резервов

**Пакет:** PR-12. **Зависимости:** 9,18,21,31. **Приёмка:** AC-32, AC-36, AC-42, AC-43, AC-48.

**Files:**
- `Modify: src/ugc_bot/container/service_factory.py`
- `Modify: src/ugc_bot/container/repository_factory.py`
- `Modify: src/ugc_bot/container/types.py`
- `Modify: src/ugc_bot/container/__init__.py`
- `Read: src/ugc_bot/application/services/support_service.py (no payout methods in current code; modify only if integration actually requires)`
- `Create: src/ugc_bot/application/services/financial_payout_gate.py`
- `Modify: src/ugc_bot/bot/telegram/handlers/referral.py`
- `Modify: src/ugc_bot/bot/max/handlers/referral.py`
- `Modify: src/ugc_bot/admin/app.py`
- `Create: tests/postgres_financial/test_legacy_v1_payout_gate.py`
- **Test target:** `tests/postgres_financial/test_legacy_v1_payout_gate.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Pending/paid legacy и новые v1 funds одного recipient/currency: старый handler/admin не может повторно выплатить migrated obligation или обойти dispute.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_legacy_v1_payout_gate.py -k test_legacy_path_cannot_bypass_wallet_freeze -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Расширить safety-guard Task05 общим ownership marker и wallet gate из ADR; не создавать вторую независимую блокировку. До завершения bridge или неизвестных legacy transfers v1 payout этой пары отключён. Нельзя складывать legacy aggregate и импортированные same-source obligations дважды.

**Step 4 — GREEN / следующие маленькие циклы:** Проверить все mark-paid/create paths: Telegram/MAX referral callbacks пишут напрямую в payout_request_repo; SQLAdmin PayoutRequestAdmin сейчас допускает редактирование status/amount без command service. Заменить обходы на gate+application command, generic edit/delete денежных полей закрыть. В support_service.py сейчас payout methods нет — не добавлять несвязанный refactor. Gate подключается раньше enabling v1_reserve и сохраняется при emergency stop.

**Step 5 — Verification / review:** поведенческий RED на исходной реализации; после minimal change GREEN на реальной PostgreSQL. Выполнять внутри test container по §3.2, не на host/production. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 38: Атомарный reserve всей доступной суммы одной валюты

**Пакет:** PR-12. **Зависимости:** 20,21,37. **Приёмка:** AC-31, AC-32, AC-34, AC-35, AC-52.

**Files:**
- `Modify: src/ugc_bot/infrastructure/db/models.py`
- `Create: src/ugc_bot/infrastructure/db/migrations/versions/<next_revision>_financial_payouts.py`
- `Create: src/ugc_bot/application/services/payout_service.py`
- `Create: src/ugc_bot/infrastructure/db/repositories/financial_payouts.py`
- `Create: tests/postgres_financial/test_payout_reservation_race.py`
- **Test target:** `tests/postgres_financial/test_payout_reservation_race.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Две concurrent requests вокруг UTC midnight: один свободный остаток нельзя зарезервировать дважды. Изменился wallet_version →409; намеренный partial →422.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_payout_reservation_race.py -k test_concurrent_full_balance_requests_reserve_once -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Wallet lock, recheck available/gate и expected_version, request+immutable allocation events+reserved transfer+outbox в одной transaction. processing_due_at=requested_at+72h UTC — SLA, не TTL резерва; overdue даёт alert, не release. Idempotency samekey samepayload возвращает прежнюю request.

**Step 4 — GREEN / следующие маленькие циклы:** Rejected/cancelled освобождают только незаблокированный остаток до банковского старта; нулевой баланс и другой currency не смешиваются.

**Step 5 — Verification / review:** поведенческий RED на исходной реализации; после minimal change GREEN на реальной PostgreSQL. Выполнять внутри test container по §3.2, не на host/production. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 39: Ручное исполнение выплаты и уникальный bank reference

**Пакет:** PR-12. **Зависимости:** 38. **Приёмка:** AC-32, AC-33, AC-34.

**Files:**
- `Modify: src/ugc_bot/application/services/payout_service.py`
- `Modify: src/ugc_bot/admin/app.py`
- `Create: tests/application/services/test_payout_service.py`
- `Create: tests/postgres_financial/test_payout_execution.py`
- **Test target:** `tests/postgres_financial/test_payout_execution.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Duplicate mark-paid/reference, другая сумма/currency, отсутствующее proof и payment_unknown не допускают фиктивный paid или второй execution.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_payout_execution.py -k test_mark_paid_requires_matching_unique_execution -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Approved→payment_in_progress→paid с immutable execution и точным allocation amount. Unknown сохраняет reserve. Сумма фактического платежа отличается → exception/reconcile, не подгонять факты и не отправлять remainder автоматически.

**Step 4 — GREEN / следующие маленькие циклы:** Manual liquidity/identity/proof review; реквизиты доступны только в защищённой админке. Система не обещает предотвратить перевод, сделанный человеком вне неё.

**Step 5 — Verification / review:** поведенческий RED на исходной реализации; после minimal change GREEN на реальной PostgreSQL. Выполнять внутри test container по §3.2, не на host/production. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 40: Гонка refund/dispute с банковским in-flight

**Пакет:** PR-12. **Зависимости:** 35,36,38,39. **Приёмка:** AC-30, AC-33, AC-49, AC-50.

**Files:**
- `Modify: src/ugc_bot/application/services/payout_service.py`
- `Modify: src/ugc_bot/application/services/refund_service.py`
- `Create: tests/postgres_financial/test_refund_during_payout.py`
- **Test target:** `tests/postgres_financial/test_refund_during_payout.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** После payment_in_progress приходит refund/issue, банковский результат ещё unknown: reserve не освобождается и не используется вторично.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_refund_during_payout.py -k test_inflight_reserve_is_not_reallocated -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Заморозить дальнейшие действия, case; получить факт банка. Если paid подтверждён — historical paid+case/debt; если достоверно не исполнен — исправить obligation и освободить допустимый остаток. Без сетевого вызова под SQL lock.

**Step 4 — GREEN / следующие маленькие циклы:** Проверить оба порядка коммитов и actual partial transfer exception; финансовая история сходится, late webhook не создаёт повтор.

**Step 5 — Verification / review:** поведенческий RED на исходной реализации; после minimal change GREEN на реальной PostgreSQL. Выполнять внутри test container по §3.2, не на host/production. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 41: DI, аутентифицированные API и адаптеры обоих мессенджеров

**Пакет:** PR-13. **Зависимости:** 23,28,30,31,34,35,38,39. **Приёмка:** AC-01, AC-02, AC-18, AC-27, AC-43, AC-52.

**Files:**
- `Create: tests/unit/test_financial_evidence_api.py`
- `Read: src/ugc_bot/application/services/support_service.py (no payout methods in current code; modify only if integration actually requires)`
- `Modify: src/ugc_bot/container/infrastructure_factory.py`
- `Modify: src/ugc_bot/container/types.py`
- `Modify: src/ugc_bot/container/service_factory.py`
- `Modify: src/ugc_bot/container/repository_factory.py`
- `Modify: src/ugc_bot/container/__init__.py`
- `Create: src/ugc_bot/miniapp/financial_api.py`
- `Modify: src/ugc_bot/miniapp/api.py`
- `Create: tests/unit/test_financial_api.py`
- **Test target:** `tests/unit/test_financial_api.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Невалидный initData, forged actor/recipient, stale expected_version и idem key с иным payload не выполняют money commands.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/unit/test_financial_api.py -k test_financial_api_reuses_authenticated_commands -v --no-cov
```

**Step 3 — Минимальная реализация:** Wiring новых ports/services в существующий Container и dispatcher; единый application command для Telegram/MAX/MiniApp/admin. Новые versioned routes через текущий mount; initData/platform signature проверяются штатно. JSON int minor units, cursor pagination и whitelist serializer. Авторизованные upload/read evidence endpoints используют EvidenceService; claim принимает только доступный ref нужной области. Payout proof admin-only, недоступен чужому пользователю или менеджеру; signed link/stream не публичный и не содержит токена. Negative API tests: foreign asset/proof, oversized, MIME mismatch и URL server-side fetch. Сначала локальный fake storage boundary, затем contract test выбранного реального adapter в isolated staging, не fake success в production.

**Step 4 — GREEN / следующие маленькие циклы:** 401/403/404/409/422 единообразны; old callbacks маршрутизируются по order policy. В handlers нет прямого SQL/admin balance field UPDATE.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 42: Партнёрское меню, прозрачные buckets и объяснение каждой суммы

**Пакет:** PR-13. **Зависимости:** 21,23,34,38,41. **Приёмка:** AC-16, AC-37, AC-39, AC-45.

**Files:**
- `Modify: tests/conftest.py (financial E2E required-mode option)`
- `Modify: .github/workflows/lint-test.yml (isolated financial WebView E2E step)`
- `Modify: tests/e2e/conftest.py`
- `Create: tests/e2e/financial_fixtures.py`
- `Modify: src/ugc_bot/application/services/referral_stats_service.py`
- `Modify: src/ugc_bot/bot/telegram/handlers/keyboards.py`
- `Modify: src/ugc_bot/bot/telegram/handlers/referral.py`
- `Modify: src/ugc_bot/bot/max/handlers/referral.py`
- `Modify: src/ugc_bot/miniapp/app.html`
- `Modify: src/ugc_bot/miniapp/max_app.html`
- `Create: tests/e2e/test_financial_wallet_ui.py`
- **Test target:** `tests/e2e/test_financial_wallet_ui.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Новый user без знания /referral находит ссылку; pending/hold/available/reserved/paid/cancelled/debt различны и раскрываются до item/base/rate/reason.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/e2e/test_financial_wallet_ui.py -k test_wallet_exposes_separate_financial_buckets -v -m e2e --timeout=90 --no-cov
```

**Step 3 — Минимальная реализация:** Собственный read facade с проверкой ownership и per currency/kind totals. Management отдельно от referral. Share intent не считать отправкой. Отдельно проверить: старый user по новой ссылке не меняет binding; новый user получает только первую допустимую binding. Не раскрывать клиентские/авторские контакты в финансовой истории.

**Step 4 — GREEN / следующие маленькие циклы:** E2E на локальном test app с fake initData verification provider, не production token; loading/error/empty/disputed и обе WebView templates. Идемпотентность withdraw request на повторном тапе.

**Step 5 — Verification / review:** поведенческий RED→GREEN на локальном isolated test app; Playwright установлен, live Telegram/MAX/bank не используется. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 43: Выбор сопровождения и lead persisted before notification

**Пакет:** PR-13. **Зависимости:** 15,16,34,41. **Приёмка:** AC-10, AC-12, AC-41.

**Files:**
- `Modify: src/ugc_bot/bot/max/handlers/order_creation.py`
- `Modify: src/ugc_bot/miniapp/app.html`
- `Modify: src/ugc_bot/miniapp/max_app.html`
- `Modify: src/ugc_bot/bot/telegram/handlers/order_creation.py`
- `Create: tests/e2e/test_accompaniment_checkout.py`
- **Test target:** `tests/e2e/test_accompaniment_checkout.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Выбрать сопровождение, повторить tap, аварийно завершить notifier: DB choice/lead один; платёж видит раздельные компоненты. Проверить тот же путь Telegram/MAX.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/e2e/test_accompaniment_checkout.py -k test_accompaniment_choice_survives_notification_failure -v -m e2e --timeout=90 --no-cov
```

**Step 3 — Минимальная реализация:** UI показывает 500/1200/итог по snapshot, сохраняет flag/позиции/контакты и consent. Отказ от сопровождения не меняет selection flow. Переиспользовать src/ugc_bot/bot/telegram/handlers/order_creation.py и src/ugc_bot/bot/max/handlers/order_creation.py; оба вызывают один application service.

**Step 4 — GREEN / следующие маленькие циклы:** После capture выбор не переписывает старую сумму; без оплаченного accompaniment нет available management. Не обещать автоматическую интеграцию банка.

**Step 5 — Verification / review:** поведенческий RED→GREEN на локальном isolated test app; Playwright установлен, live Telegram/MAX/bank не используется. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 44: Недельная сводка вместо legacy per-author cascades

**Пакет:** PR-13. **Зависимости:** 25,27,32,41. **Приёмка:** AC-21, AC-40, AC-43.

**Files:**
- `Modify: src/ugc_bot/feedback_scheduler.py`
- `Modify: src/ugc_bot/financial_scheduler.py`
- `Create: src/ugc_bot/application/services/campaign_digest_service.py`
- `Create: tests/scheduler/test_campaign_digest_scheduler.py`
- **Test target:** `tests/scheduler/test_campaign_digest_scheduler.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** 30 authors в v1 order не создают legacy reminder cascade; одна digest на recipient/order/week, пустая не отправлена.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/scheduler/test_campaign_digest_scheduler.py -k test_thirty_creators_get_one_campaign_digest -v --no-cov
```

**Step 3 — Минимальная реализация:** Уникальный digest key/timezone и агрегирование counts. Операционные claim/objection/refund/payout сообщения отдельные. Старый scheduler явно исключает v1, не отключается глобально для legacy.

**Step 4 — GREEN / следующие маленькие циклы:** Два workers и retry не создают две business digests; пакетное редактирование статусов вне B, отсутствие отзыва не равно опубликованному ролику.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 45: Read-only preflight и идемпотентный legacy bridge

**Пакет:** PR-14. **Зависимости:** 21,37,39. **Приёмка:** AC-07, AC-09, AC-42, AC-48.

**Files:**
- `Modify: src/ugc_bot/infrastructure/db/repositories/financial_ledger.py`
- `Create: scripts/financial_reconciliation.py`
- `Create: scripts/financial_migration.py`
- `Create: src/ugc_bot/application/services/financial_migration_service.py`
- `Create: tests/postgres_financial/test_legacy_bridge.py`
- **Test target:** `tests/postgres_financial/test_legacy_bridge.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Synthetic legacy paid/pending/duplicate binding/case/unknown bank state: dry-run ничего не пишет; повтор импорта не дублирует money; paid не становится available.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_legacy_bridge.py -k test_bridge_never_reopens_paid_or_reserved_income -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Default --dry-run; report source IDs, per currency balances и blocked anomalies. Bridge deterministic source keys и ownership marker; write только отдельным --apply с подтверждённым cutover и shared wallet lock. Unknown исполнение сначала сверяется, не мигрирует как свободное.

**Step 4 — GREEN / следующие маленькие циклы:** Исключения делают конкретную миграцию blocked, не silent skip с зелёным total. Никаких production SQL в автотесте. Старые суммы не пересчитываются новой ставкой.

**Step 5 — Verification / review:** поведенческий RED на исходной реализации; после minimal change GREEN на реальной PostgreSQL. Выполнять внутри test container по §3.2, не на host/production. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 46: Writer barrier, cutover и безопасный rollback

**Пакет:** PR-14. **Зависимости:** 12,16,25,37,45. **Приёмка:** AC-42, AC-43, AC-44, AC-48.

**Files:**
- `Modify: src/ugc_bot/application/services/financial_migration_service.py`
- `Modify: src/ugc_bot/application/services/referral_income_recorder.py`
- `Modify: src/ugc_bot/referral_reconciliation_scheduler.py`
- `Create: tests/postgres_financial/test_cutover_writer_barrier.py`
- `Create: docs/runbooks/financial-v1-cutover.md`
- **Test target:** `tests/postgres_financial/test_cutover_writer_barrier.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Legacy job/old callback одновременно с transfer/rollback не пишет новый income и не отмечает вторую выплату migrated source. Unpaid old order не становится v1.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_cutover_writer_barrier.py -k test_legacy_writer_is_fenced_after_transfer -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Policy at order creation после technical effective_from, retain at capture. Consumer/writer ownership check обязателен внутри transaction. Старый бинарник без marker-support не запускать для денежных writes; freeze+forward-fix вместо downgrade с удалением ledger.

**Step 4 — GREEN / следующие маленькие циклы:** Flags off не удаляют долги, не отключают intake objections/refunds/reconciliation. Plan restore проверяется на копии с synthetic данными, не на production.

**Step 5 — Verification / review:** поведенческий RED на исходной реализации; после minimal change GREEN на реальной PostgreSQL. Выполнять внутри test container по §3.2, не на host/production. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 47: Финансовая админка, защитные алерты и runbooks

**Пакет:** PR-15. **Зависимости:** 21,31,36,39,41,46. **Приёмка:** AC-32, AC-33, AC-36, AC-45.

**Files:**
- `Modify: config/monitoring/prometheus.yml`
- `Read: src/ugc_bot/metrics/collector.py`
- `Read: src/ugc_bot/telegram_webhook_app.py, src/ugc_bot/max_webhook_app.py`
- `Modify: src/ugc_bot/admin/app.py`
- `Create: src/ugc_bot/metrics/financial.py`
- `Modify: config/monitoring/alerts.yml`
- `Create: docs/runbooks/financial-v1-operations.md`
- `Create: tests/admin/test_financial_operations.py`
- **Test target:** `tests/admin/test_financial_operations.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Admin видит origin/assignment/snapshot/journal/delivery/case/payout trace; arbitrary editable balance и leaks банковских реквизитов недоступны.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/admin/test_financial_operations.py -k test_admin_sees_trace_without_editable_balance -v --no-cov
```

**Step 3 — Минимальная реализация:** Очередь delivery_blocked/unknown, overdue hold/payout и reconciliation mismatch. Alerts per currency; no-card-data logs; права по роли. Новые metrics только через existing exporter wiring, не новый неподтверждённый public service.

**Step 4 — GREEN / следующие маленькие циклы:** Проверить durable audit чтения/выдачи материалов и payout proof с actor/resource/time, ACL разных ролей, audit изменения и закрытие expired доступа; не ограничиваться фильтрацией логов. Затем runbook manual unknown resolution и emergency stop. Правила в config/monitoring/alerts.yml, scraping в config/monitoring/prometheus.yml; общий metrics registry и существующие /metrics endpoints. Метрики отдельного scheduler должны действительно экспортироваться (existing shared exporter/aggregate), не только существовать в его локальной памяти.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 48: Полный synthetic E2E на 30 позициях и регрессии платформ

**Пакет:** PR-15. **Зависимости:** 28,33,34,40,42,43,44,46,47. **Приёмка:** AC-10, AC-11, AC-12, AC-16, AC-20, AC-23, AC-26, AC-27, AC-29, AC-30, AC-31, AC-34, AC-37, AC-40, AC-44, AC-49, AC-50, AC-51, AC-52.

**Files:**
- `Read: tests/e2e/financial_fixtures.py`
- `Create: tests/e2e/test_financial_order_lifecycle.py`
- `Create: tests/postgres_financial/test_financial_lifecycle.py`
- **Test target:** `tests/postgres_financial/test_financial_lifecycle.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Синтетический order: capture, 25 delivered/5 refund, замена, 20 successes, failure/unknown notifications, dispute, full reserve и manual simulated payout.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
python -m pytest tests/postgres_financial/test_financial_lifecycle.py -k test_thirty_item_financial_lifecycle -v --no-cov --require-financial-postgres --timeout=60
```

**Step 3 — Минимальная реализация:** Соединить реальные services/repositories, fake только external messenger/bank boundary; использовать управляемый clock. Сверить каждое основание и G/V/F/R/U/D. На UI пройти auth и действия без live credentials.

**Step 4 — GREEN / следующие маленькие циклы:** Не ждать реальные14 дней в тестах; отдельные contract tests подтверждают actual dates. Не подменять искусственный provider success реальной выплатой или production кейсом.

**Step 5 — Verification / review:** поведенческий RED на исходной реализации; после minimal change GREEN на реальной PostgreSQL. Выполнять внутри test container по §3.2, не на host/production. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 49: Пилотный release checklist и stage B readiness

**Пакет:** PR-15. **Зависимости:** 48. **Приёмка:** AC-36, AC-42, AC-43, AC-44, AC-45, AC-51.

**Files:**
- `Create: docs/runbooks/financial-v1-release-checklist.md`
- `Create: tests/application/services/test_financial_release_readiness.py`
- **Test target:** `tests/application/services/test_financial_release_readiness.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Не задан возвратный срок/selection_due_at, нет writer barrier/consumer readiness или legal receipt: activation запрещена, независимо от accepted D-xx.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_financial_release_readiness.py -k test_missing_policy_or_worker_blocks_activation -v --no-cov
```

**Step 3 — Минимальная реализация:** Собрать проверяемый checklist accepted policy, параметры, migration report, zero discrepancy, alerts/owners, restricted allowlist и тест emergency stop. Сама задача пишет артефакты и валидатор, не включает production.

**Step 4 — GREEN / следующие маленькие циклы:** Реальное enable/deploy требует отдельного запроса, сверенного CI ≥98% и операционного sign-off. Product KPI14d не отменяет hold и не доказывает выплату.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 50: C: social_accounts без раздвоения creator identity

**Пакет:** PR-16. **Зависимости:** 22,49. **Приёмка:** AC-14, AC-46.

**Files:**
- `Create: src/ugc_bot/infrastructure/db/migrations/versions/<next_revision>_social_accounts.py`
- `Create: src/ugc_bot/application/services/social_account_service.py`
- `Modify: src/ugc_bot/infrastructure/db/models.py`
- `Create: src/ugc_bot/infrastructure/db/repositories/social_accounts.py`
- `Create: tests/application/services/test_social_account_service.py`
- **Test target:** `tests/application/services/test_social_account_service.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Один creator имеет Instagram/TikTok/YouTube/Telegram/VK; дополнительных verified creators не возникает, telegram contact не путается с channel.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/application/services/test_social_account_service.py -k test_extra_social_accounts_do_not_increase_grade -v --no-cov
```

**Step 3 — Минимальная реализация:** Нормализовать platform/account ID, сохранять verification state отдельно; Instagram остаётся обязательным. Create social accounts migration после актуального head. Конфликт identity → review, не auto-merge.

**Step 4 — GREEN / следующие маленькие циклы:** Unverified внешняя сеть не влияет на грейд; старые профили/регистрация продолжают работать.

**Step 5 — Verification / review:** один ожидаемый assertion RED, затем GREEN; после этого весь файл и связанные legacy tests. Изолированное окружение §3.1. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 51: C: шаги дополнительных соцсетей и честная статистика

**Пакет:** PR-16. **Зависимости:** 50. **Приёмка:** AC-46.

**Files:**
- `Modify: src/ugc_bot/application/services/blogger_registration_service.py`
- `Modify: src/ugc_bot/bot/telegram/handlers/blogger_registration.py`
- `Modify: src/ugc_bot/bot/max/handlers/blogger_registration.py`
- `Modify: src/ugc_bot/miniapp/api.py`
- `Create: tests/e2e/test_social_accounts_ui.py`
- **Test target:** `tests/e2e/test_social_accounts_ui.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** После Instagram предложены последовательно доступные площадки; отказ/ошибка API показывает нет данных, не вымышленные нули/verified.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/e2e/test_social_accounts_ui.py -k test_unavailable_social_stats_are_not_zero_or_verified -v -m e2e --timeout=90 --no-cov
```

**Step 3 — Минимальная реализация:** Использовать существующие blogger_registration.py обоих мессенджеров и blogger_registration_service.py; skip optional networks и timestamps/source. Не добавлять scraping/новые API креды без отдельного выбора источника.

**Step 4 — GREEN / следующие маленькие циклы:** WebView ввод/валидация URL, возврат без повторной регистрации; profile identity и grade неизменны.

**Step 5 — Verification / review:** поведенческий RED→GREEN на локальном isolated test app; Playwright установлен, live Telegram/MAX/bank не используется. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

### Task 52: C: дизайн-токены и расширенный кабинет без переписывания checkout

**Пакет:** PR-17. **Зависимости:** 49,50,51. **Приёмка:** AC-01, AC-39, AC-46.

**Files:**
- `Modify: src/ugc_bot/miniapp/app.html`
- `Modify: src/ugc_bot/miniapp/max_app.html`
- `Modify: src/ugc_bot/miniapp/api.py`
- `Create: tests/e2e/test_financial_webview_regression.py`
- **Test target:** `tests/e2e/test_financial_webview_regression.py` (новые selectors создать в рамках задачи).

**Step 1 — RED, один тест:** Получить реальные tokens/mockups; зафиксировать smoke рабочих registration/checkout/manager/wallet routes до визуальных изменений.

**Step 2 — Выполнить и зафиксировать причину:**

```bash
uv run pytest tests/e2e/test_financial_webview_regression.py -k test_existing_checkout_and_financial_states_survive_theme -v -m e2e --timeout=90 --no-cov
```

**Step 3 — Минимальная реализация:** Применить согласованные tokens, safe area/keyboard/mobile errors; собственная сеть и прогресс грейда через существующие backend services. Нет full migration/PWA и нового альтернативного financial calculator в JS.

**Step 4 — GREEN / следующие маленькие циклы:** iOS/Android Telegram и MAX WebView matrix; если токены не переданы — только C задача заблокирована, A/B не задерживаются.

**Step 5 — Verification / review:** поведенческий RED→GREEN на локальном isolated test app; Playwright установлен, live Telegram/MAX/bank не используется. Review diff по спецификации и безопасности; только после разрешения на код — scoped commit, без автоматического merge/deploy.

## 5. Три стартовых кодовых контракта (только примеры для плана)

Ниже полные маленькие образцы для задач5/11. Это **не созданные файлы и не запущенный код**. Их не копировать в production до RED. Остальные service interfaces уточняются по ports/ADR до конкретного теста; не писать заранее тысячи строк по выдуманной сигнатуре.

### 5.1. Реальный regression против текущего агрегатора

Добавить в `tests/application/services/test_interaction_service.py`:

```python
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.domain.enums import InteractionStatus


def test_conflicting_feedback_opens_issue() -> None:
    result = InteractionService._aggregate(
        "✅ Всё прошло успешно", "❌ Не договорились"
    )
    assert result is InteractionStatus.ISSUE
```

RED ожидается по assert, не из-за отсутствия import. Minimal GREEN — проверить пару OK/NO_DEAL после ISSUE-приоритета до правила any OK. Затем отдельные service-level тесты доказывают, что result сохраняется и не вызывает income; одного private helper теста недостаточно для AC-03.

### 5.2. Новый minor-unit контракт

Будущий файл `tests/application/services/test_financial_math.py`:

```python
import pytest

from ugc_bot.domain.financial import commission_minor


@pytest.mark.parametrize(
    ("base_minor", "rate_bps", "expected"),
    [(50000, 1000, 5000), (50000, 2000, 10000), (1, 5000, 1)],
)
def test_financial_math_boundaries(
    base_minor: int, rate_bps: int, expected: int
) -> None:
    assert commission_minor(base_minor, rate_bps) == expected
```

После минимального declaration, behavioural RED и подтверждённого теста minimal implementation:

```python
from decimal import Decimal, ROUND_HALF_UP


def commission_minor(base_minor: int, rate_bps: int) -> int:
    if type(base_minor) is not int or type(rate_bps) is not int:
        raise TypeError("integer minor units and basis points required")
    if base_minor < 0 or not 0 <= rate_bps <= 10000:
        raise ValueError("invalid commission input")
    value = Decimal(base_minor) * Decimal(rate_bps) / Decimal(10000)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
```

Контракт10000bps — техническая валидность Decimal helper, **не разрешение overrides до100%**. Policy отдельно запрещает v1 overrides D-07 и возвращает только стандартные rates. Следующие RED отдельно для bool/float/negative/range и partial/full reversal cumulative rounding.

### 5.3. Календарная годовщина UTC без365.25

```python
from datetime import datetime, timezone


def first_anniversary(registered_at: datetime) -> datetime:
    if registered_at.tzinfo is None or registered_at.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    value = registered_at.astimezone(timezone.utc)
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        if value.month == 2 and value.day == 29:
            return value.replace(year=value.year + 1, day=28)
        raise
```

Сначала тесты before/exact/after anniversary, leap day и naive rejection. Legacy years_since/resolve_rate остаются legacy; функции не подменяются глобальным rename.

## 6. Контракты интеграции, которые нельзя пропустить

### 6.0. Каждый промежуточный PR работоспособен

DI/dispatcher wiring добавляется **в том же task/PR, где новая зависимость впервые нужна действующему legacy path**. Task41 — финальная сборка и публичные финансовые API, не разрешение оставлять сломанные конструкторы до конца проекта. Task05 уже подключает legacy guard и его repository/port в Container; Task37 расширяет тот же сервис/gate и wiring. Для обновлённых registration/verification/feedback services и каждого нового worker — startup test с flags off, защищённый legacy flow и readiness с flags on. Если нужен дополнительный DI-файл, включать его в текущий scoped PR, не обходить инъекцию через прямой SQL в handler.

Ранние v1 stages могут сохранять типизированный outbox event до наличия consumer в изолированном тесте; в реальной среде producers остаются выключены до Task25/49. Нельзя получить GREEN fake-уведомлением при отсутствующем реальном adapter. Constructor compatibility контролируется полным legacy suite, не произвольными default=None с тихим обходом финансовой защиты.

### 6.1. Transactions и порядок блокировок

- Все repositories пишут в переданный session, а не открывают независимую transaction посреди команды.
- Координационный lock `(recipient_id,currency)` одинаковый для legacy/v1 payout, ledger freeze и reserve; затем items/obligations/request по сортированному порядку ADR. Получатели определяются по snapshot, после lock ownership/version проверяются заново.
- Платёж, item allocations, snapshot/obligation requests и outbox атомарны. Отправка messenger/bank не держит SQL lock.
- Финансовая команда не ждёт Kafka/Telegram внутри transaction. Потерянный ack может дать duplicate transport, но не duplicate money.
- Journal append-only проверяется non-owner DB role; backup/migration owner отдельно. ORM запрет UPDATE сам по себе недостаточен.

### 6.2. Event routing и worker readiness

Текущий OutboxPublisher/OutboxProcessor ориентирован на order.activated/OrderActivationPublisher. Его нельзя считать универсальной финансовой шиной. Task25 добавляет и проверяет явный routing до включения финансовых producers. Неизвестные финансовые типы не помечаются processed, не активируют заказ и не воруют события друг у друга.

`financial_scheduler` стартует через документированный container/entrypoint и ограниченные batches; health/readiness подтверждает policy, routing, schema и отсутствие shutdown flags. Kafka disabled/отсутствующий consumer при обязательной доставке — fail-closed. Повторная обработка event ID сверяет payload hash.

### 6.3. UI и авторизация

Только backend рассчитывает деньги, ownership и deadlines. UI показывает int minor/currency и объяснения, не вычисляет второй независимый баланс. Claims и confirmation связаны с immutable evidence refs/version; proof не публичный Telegram чат. MAX и Telegram вызовы равнозначны по бизнес-правам, но transport acceptance фиксируется для выбранного канала отдельно.

### 6.4. Изменения схемы и legacy compatibility

Каждый migration revision выбирается после реального head; новые поля nullable/с явным discriminator для старых записей. Не импортировать v1 snapshot/backfill по текущему грейду для прошлых операций. Immutable ledger нельзя down-migrate с удалением данных. Zero-downtime приложение поддерживает dual read до cutover; old writers ограждены marker внутри transaction. Старый бинарник, игнорирующий marker, не годится для денежного rollback.

### 6.5. Карта миграций и schema parity по этапам

Все Create-репозитории требуют не только Python-методы, но и соответствующую Alembic revision/ORM schema. Сначала schema regression RED на isolated PostgreSQL, затем migration+model, upgrade с synthetic legacy seed, затем repository/service:

| Задача | Что хранит новая схема |
|---|---|
| 05 | durable wallet safety-guard для legacy Issue и выплаты; координационная строка переиспользуется v1 |
| 09 | parity существующих income unique и первая активная binding |
| 14 | financial policies, paid items, components/allocations и versioned assignments |
| 18 | obligations, append-only journal, rate snapshots, wallet projections и ownership/writer markers; safety/coordination row Task05 переиспользуется |
| 22 | verified identity/count events и исходный grade snapshot |
| 26 | durable inbox с producer/event uniqueness, received_at и payload hash |
| 27 | notification request/delivery attempts, accepted/unknown/recovery timestamps и business key |
| 29 | collaboration/versioned brief, claim, due/objection timestamps, protected evidence metadata/owner/ACL/retention и refs |
| 31 | cases, earliest received safety-stop и связь с затронутыми основаниями |
| 34 | management entitlement versions/recipient change history |
| 35 | refund components/statuses, external reference и source allocations |
| 38 | payout requests, immutable allocation/execution events, unique(provider, account, bank reference) |
| 50 | optional social_accounts; canonical identity и verification отдельно |

Если одинаковая таблица уже создана предыдущим шагом, новая revision только расширяет её; не создавать второй competing source of truth. Immutable snapshots сохраняются в Task18, Task23 реализует их семантическое заполнение. Ownership markers существуют до gate/bridge, не добавляются задним числом после первых выплат. Для любой таблицы с личными данными определяется ACL/retention; proofs хранятся ссылками с доступом, не публичными raw payload.

Shared Base.metadata затрагивает существующие SQLite fixtures. На каждой schema-задаче прогонять их smoke: типы делать portable где это не ослабляет PG-инварианты (например JSON с PostgreSQL variant), PG-only DDL — dialect-specific. Исключение v1-only tables из конкретной SQLite fixture допускается только при отдельном обязательном PG coverage соответствующего сервиса; не маскировать constraints и миграции unit fake-схемой.

### 6.6. E2E не должен чистить чужую БД и молча skip

В tests/e2e/conftest.py уже есть cleanup по E2E_DATABASE_URL и Mini App fixtures, которые skip без E2E_MINIAPP_URL/E2E_BOT_TOKEN. Очистка унаследованных переменных обязательна уже до Task01; guard cleanup внедряется в Task02, не откладывается до UI. Перед новым финансовым E2E в Task42:

- повторно проверить guard Task02 для любого cleanup до DELETE; только отдельная проверенная тестовая БД, никаких production `.env`;
- создать financial_fixtures.py с локальным временным Mini App app/Container, синтетическим валидным test-only bot token, fake external messenger/bank и тестовой PG;
- новый financial fixture не использует remote Mini App URL по умолчанию и не требует живого bot token;
- new tests пометить e2e; отсутствие нужного local server/PG в обязательном E2E job — error, не skip;
- установить Chromium заранее `uv run python -m playwright install chromium`; app readiness подтверждается health check, URL возвращает fixture;
- старые optional live Telegram e2e остаются opt-in и не запускаются этим планом.

Для команд Task42/43/51/52 нужны эти fixtures; в Task48 добавить полный UI сценарий. Дополнительный CI E2E шаг/ job — обязательный для затронутых WebView-фич, полный unit/PG coverage он не подменяет.

## 7. Матрица приёмки → конкретные задачи

Здесь критерии переписаны из принятой спецификации1.2, а не придуманы как новое продуктовое решение. Один AC может иметь несколько уровней: unit, PostgreSQL, adapter, E2E. Покрытие строкой таблицы не означает, что тест уже написан или пройден.

| AC | Основные задачи | Требование |
|---|---|---|
| AC-01 | 03, 04, 41, 52 | менеджер A в том же заказе не получает контакт и не меняет данные автора менеджера B через detail/video/remove/feedback; admin исключение разрешено и журналируется. |
| AC-02 | 04, 41 | feedback для blogger_id без соответствующего dispatch/assignment отклоняется без создания Interaction. |
| AC-03 | 05, 31 | success + no_deal → спор; issue + молчание → safety-stop, не возможность выплаты. |
| AC-04 | 06, 27 | retry=False → delivery failed; следующий бизнес-таймер не стартует как после успешной доставки. |
| AC-05 | 08 | два автора одного партнёра в одном заказе: наличие первого income не скрывает пропущенное второе в reconciliation. |
| AC-06 | 07 | возврат из резерва: фактическое назначение и контакт в уведомлении совпадают. |
| AC-07 | 09, 14, 45 | ORM metadata и мигрированная схема имеют согласованные unique constraints; проверка на реальном тестовом PostgreSQL, не только fake. |
| AC-08 | 10, 16 | повтор capture webhook после смены статуса заказа возвращает исходный payment/result, не создаёт второй платёж и не падает только из-за статуса NEW. |
| AC-09 | 09, 10, 45 | конкурентные referrals не создают двух активных партнёров одного referred_user. |
| AC-10 | 11, 14, 15, 16, 17, 43, 48 | стандартные 50000 + 120000 = 170000 minor units на позицию; цена/валюта сохраняются и не меняются от нового тарифа. |
| AC-11 | 28, 48 | 30 оплачено, 25 передано, 5 возвращено: selection base 1250000 minor, клиентская комиссия при 10% — 125000 minor; непереданные позиции недоступны к выплате. |
| AC-12 | 15, 16, 23, 28, 35, 43, 48 | сопровождение не включается ни в клиентскую, ни в авторскую реферальную базу. |
| AC-13 | 11, 23 | старый партнёр и недавно зарегистрированный приглашённый: первый год определяется по приглашённому в принятой политике. |
| AC-14 | 11, 22, 23, 50 | пороги 99/100/199/200/399/400 verified переключают только авторский грейд; неverified и дополнительные соцсети не увеличивают счётчик. |
| AC-15 | 11, 12, 17, 22, 23 | изменение грейда после snapshot не меняет старую операцию; новый v1 override отклонён по D-07. Клиентский snapshot при capture, авторский при оплаченном назначении и замене; до/на календарной годовщине и для 29 февраля проверены выбранные ставки D-01/D-06. |
| AC-16 | 18, 19, 23, 34, 42, 48 | один получатель обеих сторон получает два основания; повтор события не создаёт третье. |
| AC-17 | 24 | замена отменяет старое ожидающее авторское основание, создаёт новое и не повторяет клиентскую комиссию; после выполнения обычная замена запрещена. |
| AC-18 | 29, 41 | claim без допустимого evidence отклонён; менеджер не подтверждает себе выплату в обход D-04. |
| AC-19 | 25, 27, 30 | заявление успеха → один business notification; дубликат callback не создаёт новое окно. |
| AC-20 | 31, 33, 48 | возражение на 71-м часу → спор и заморозка, комиссия не available. |
| AC-21 | 32, 44 | обе стороны молчат до due_at+14d → unconfirmed_expired; нет успешной публикации и заработка. |
| AC-22 | 32 | claim до expiry → полное окно возражения, даже если оно заканчивается после due_at+14d. |
| AC-23 | 20, 28, 30, 32, 33, 48 | отсутствие возражения по принятой D-03 → success_final, но не available до окончания 14 суток hold. |
| AC-24 | 27, 30 | ошибка/unknown доставки не приводит к автоуспеху; после восстановления срок соответствует выбранной политике. |
| AC-25 | 29, 32 | deadline extension версионируется, не скрытно сбрасывает claim/objection. |
| AC-26 | 20, 31, 33, 36, 48 | поздний спор после успеха блокирует соответствующий остаток; после paid сохраняет платёж и создаёт case/debt, без скрытого переписывания. |
| AC-27 | 16, 18, 19, 25, 26, 33, 41, 48 | повтор webhook/event/manual retry и два workers дают одно обязательство на основание. |
| AC-28 | 13, 18, 19, 20, 21 | разные корректировки одного обязательства разрешены, повтор одной — нет; полный replay воспроизводит projection. |
| AC-29 | 26, 35, 48 | capture/refund в обратном порядке дают тот же итог, что в прямом. |
| AC-30 | 35, 36, 40, 48 | возвраты на pending, hold, available, reserved и paid сохраняют историю и соблюдают сценарии раздела 9. |
| AC-31 | 38, 48 | два одновременных payout requests не резервируют одни и те же средства, включая гонку через UTC-полночь. |
| AC-32 | 37, 38, 39, 47 | payout с открытым case блокируется; reserve не освобождается просто через 72 часа. |
| AC-33 | 39, 40, 47 | duplicate mark-paid и повтор bank reference не создают вторую учётную выплату; payment_unknown не разрешает повторить перевод. |
| AC-34 | 25, 26, 27, 38, 39, 48 | сбой Telegram после создания заявки не теряет request/reserve; retry уведомления безопасен. |
| AC-35 | 11, 13, 20, 35, 38 | partial rounding/full reversal не отменяют больше исходной комиссии; currencies не смешиваются. |
| AC-36 | 20, 21, 37, 47, 49 | расхождение projections/ledger блокирует затронутую новую выплату и создаёт alert. |
| AC-37 | 34, 42, 48 | 20 успешно завершённых оплаченных сопровождений → 1200000 minor gross менеджеру; за 10 незавершённых нет доступного вознаграждения. |
| AC-38 | 17, 24, 29, 34 | смена менеджера не меняет получателя старого вознаграждения без versioned решения; один аккаунт может иметь отдельные referral/management доходы. |
| AC-39 | 42, 52 | новый пользователь находит партнёрскую ссылку без знания команды; суммы всех buckets раскрываются до основания. |
| AC-40 | 44, 48 | 30 авторов не порождают старый каскад оценочных запросов; важные операционные сообщения остаются. |
| AC-41 | 15, 34, 43 | новая оплаченная опция сохраняется до уведомления, повтор клика не создаёт второго lead; без оплаты management не available. |
| AC-42 | 14, 37, 45, 46, 49 | legacy paid/pending payouts после миграции не становятся доступными повторно; мост импорта идемпотентен. |
| AC-43 | 12, 23, 25, 37, 41, 44, 46, 49 | старый callback/worker не обходит v1 lifecycle и не создаёт legacy income для v1 заказа. |
| AC-44 | 12, 46, 48, 49 | emergency stop не удаляет долги и не мешает принять претензию/возврат; восстановление возобновляет обработку без дублей. |
| AC-45 | 42, 47, 49 | неутверждённые экспирация/удержания выключены; пользователю показывается согласованная gross/net-информация. |
| AC-46 | 22, 50, 51, 52 | C-релиз: единый creator с несколькими сетями считается один раз; unverified статистика помечена, ошибки API не превращаются в выдуманные данные. |
| AC-47 | 24, 35 | частичный selection-возврат → замена → успех: новый автор получает комиссию только с актуальной невозвращённой базы той же позиции; старое основание отменено атомарно; новая аллокация оплаты не возникает. |
| AC-48 | 37, 45, 46 | legacy payout worker/callback, одновременно с cutover/rollback, не может изменить или повторно выплатить перенесённое v1 основание; общий gate учитывает reserve/paid ровно один раз. |
| AC-49 | 40, 48 | refund/dispute в гонке с payment_in_progress/unknown не освобождает in-flight reserve; подтверждённая выплата остаётся фактом, корректировка переходит в case/debt; несовпадающая фактическая сумма вызывает разбор, а не повторный перевод. |
| AC-50 | 13, 18, 21, 36, 40, 48 | replay из неизменяемых событий восстанавливает allocations, block/unblock и связи с выплатами; `G - V - F + R = U - D` соблюдается отдельно по каждой валюте/получателю после возвратов и погашения долга. |
| AC-51 | 12, 15, 28, 48, 49 | без selection_refund_window или согласованного selection_due_at новый v1 тариф/capture не разрешён; существующий pending не становится available из-за отсутствующей конфигурации. Юридический release gate не считается выполненным автоматически. |
| AC-52 | 38, 41, 48 | вся доступная сумма одной валюты резервируется атомарно по D-10; произвольный partial amount запрещён, изменение available после экрана даёт 409 без частичного резерва. Налогового 6% и сгорания нет. |

## 8. Gate A, Gate B и пилот

### Gate A — можно выпускать стабилизацию отдельно

Tasks1–10: green CI с реальным baseline≥98%, manager-pair regression, service feedback conflict, работающий durable legacy dispute/payout guard (не отложен до B), transport False, два referred creators SQL, constraints/races и payment replay. Исторические финансовые аномалии только в отчёте; не делать массовое «исправление» прошлых денег.

### Gate B — до включения новых денежных операций

Tasks11–49 завершены по релизной области; 51 AC, кроме C-specific AC-46, проверены нужными уровнями. Verified unique-count часть AC-46, необходимая грейдам, уже проверяется Task22; собственно дополнительные сети/UX — C.

Обязательны:
- Принятая спецификация1.2 и policy версия в данных; D-01–D-10 не заменены другой интерпретацией.
- Заполнены selection_refund_window, согласованные сроки и формальные условия выплат; без них activation test падает.
- Full coverage≥98%, format/lint/typecheck; настоящий PostgreSQL constraints, permission tests, races/replay и migration bridge.
- Zero discrepancy отдельно recipient/currency/source, ни одного неизвестного банковского transfer в включаемой области.
- Delivery blocked/unknown и timely objection не приводят к выплатам; unknown banking не освобождает reserve.
- Общий payout gate и legacy ownership markers реально работают во всех старых entry points.
- Назначены операционные владельцы refund/dispute/payout/alerts; тест остановки и восстановления без удаления обязательств.

### Пилот после отдельного разрешения

1. Read-only preflight на целевой среде, согласованный backup/restore rehearsal на изолированной копии, утверждённый deployment manifest.
2. Код/схема сначала с flags off; проверить health/readiness и отсутствие новых ошибок.
3. Allowlist одного ограниченного заказа/участников с существующими источниками оплаты; snapshot условий до capture.
4. Проверять **каждое** основание, delivery, due/objection/hold timestamps и balances, а не только итог по заказу.
5. Реальные14/72 часа/сутки не ускорять в production. Clock travel допустим только в synthetic tests.
6. Manual payout только после реального истечения удержаний, проверки документов/ликвидности/резерва и отдельного approval. Тестовый mock не является доказательством денежного перевода.
7. При incident — отдельные flags: запрет новых captures, auto-confirm, hold release, reserve/execution. Intake претензий/возвратов и аудит продолжаются.
8. Общий запуск после принятия фактических результатов пилота, не автоматически по истечении недели или числу регистраций.

## 9. Риски и что остаётся входными данными

- Длительность возвратного окна в1.2 не задана числом. План не выдаёт7/14 дней за одобренное значение: обязательный параметр опубликованной политики до продажи. Hold14 дней — отдельный параметр, не подмена refund window.
- Налоговые статусы, реквизиты, договоры и сроки хранения требуют настоящего юридического/бухгалтерского процесса. Нельзя поставить флаг «проверено» только по принятому D-10.
- Человек может ошибочно перечислить деньги вне интерфейса. Система фиксирует факты/unknown, уникальные executions и блокировки; не обещает внешний exactly-once manual bank transfer.
- Схема actual verified identity и связь пользователей Telegram/MAX должны пройти data audit: одинаковый Telegram ID/username сам по себе не доказывает уникального человека.
- Старые тесты закрепляют старые ставки/feedback. Менять ожидания только version-aware; нельзя массово переписать legacy tests под новые правила и заявить отсутствие регрессий.
- Не менять все float money поля разом: v1 minor-unit boundary + legacy adapter, затем отдельная миграция при необходимости.
- Новые generic event routing и payout gate — критические зависимости, не косметика. Нельзя «потом добавить worker» после включения producer.
- Сроки задач не являются обещанием спринта. Финансовые этапы содержат интеграционные/операционные ворота; по результатам Tasks1–10/14/18 переоценить объём. При ограничении времени сокращать C/визуальную полировку, не ledger/dispute/race tests.

## 10. Handoff разработчику и чек-лист исполнения

- [ ] Уточнить текущие main/spec SHA и статус PR147; не выполнять план по старой версии, если документ изменился.
- [ ] Получить отдельное разрешение на кодовую реализацию. План сам ничего не запускает.
- [ ] Прочитать CLAUDE.md; feature branches, не прямые изменения main. Если spec PR не merged, оформить зависимость, не скрытно включать чужие commits.
- [ ] Создать isolated checkout/test environment без production.env; baseline и PG guard первыми.
- [ ] На каждый Task: один behavioural RED→minimal GREEN→legacy regression→refactor; воспроизводящие логи сохранять в PR.
- [ ] Не параллелить migrations, models.py и общие money interfaces без явного владельца. Параллельно допустимы независимые тестовые/adapter задачи после замораживания contracts.
- [ ] На PR boundary: независимая проверка spec compliance, security/correctness и full quality gates. Не merge failed/pending CI.
- [ ] Commit/push/merge/deploy — только в рамках отдельно порученного execution workflow; здесь не сделаны.
- [ ] Отчёт готовности различает tests passed, coverage failure, synthetic E2E и реальные внешние денежные факты.

**Артефакт этого запроса:** только данный план. Ни production, ни приложение, ни PR147 этим planning turn не изменяются.
