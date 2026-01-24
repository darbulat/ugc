# Filebeat Configuration

Filebeat собирает логи из Docker контейнеров и отправляет их в Elasticsearch.

## Конфигурация

- Логи собираются из всех контейнеров проекта
- JSON логи автоматически парсятся и структурируются
- Логи приложения индексируются в `ugc-logs-YYYY.MM.DD`
- Остальные логи индексируются в `docker-logs-YYYY.MM.DD`

## Требования

Для работы Filebeat требуется:
- Доступ к Docker socket (`/var/run/docker.sock`)
- Доступ к логам контейнеров (`/var/lib/docker/containers`)
- Подключение к Elasticsearch

Все это настроено автоматически в `docker-compose.yml`.
