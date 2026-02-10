# Первое получение SSL на dev (dev.usemycontent.ru)

Если nginx падает с «cannot load certificate» (сертификатов ещё нет), сделайте так.

## 1. Откройте порт 80 в панели хостинга

В фаерволе / security group провайдера разрешите входящий **TCP 80** на сервер.

## 2. Поднимите nginx в режиме «только HTTP»

Так nginx не будет требовать сертификаты и перестанет перезапускаться:

```bash
docker compose -f docker-compose.yml -f docker-compose.bootstrap-dev.yml up -d
```

Проверьте, что контейнер работает и порт 80 отвечает:

```bash
docker compose -f docker-compose.yml -f docker-compose.bootstrap-dev.yml ps nginx
curl -I http://dev.usemycontent.ru/
```

## 3. Получите сертификат Let's Encrypt

В `nginx/init-letsencrypt.sh` задайте домен и email:

- `domains=(dev.usemycontent.ru)`
- `email="your@email.com"`

Запускайте скрипт **с bootstrap-override**, чтобы nginx оставался в режиме «только HTTP» и не падал из‑за отсутствия сертификатов:

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.bootstrap-dev.yml ./nginx/init-letsencrypt.sh
```

При вопросе про замену существующих данных можно ответить `y`. После успешного получения сертификата переходите к шагу 4.

Если снова «Connection refused» — порт 80 с интернета до сервера не доходит (проверьте шаг 1 и DNS).

## 4. Переключитесь на HTTPS

Остановите bootstrap и запустите конфиг с HTTPS и сертификатами dev:

```bash
docker compose -f docker-compose.yml -f docker-compose.bootstrap-dev.yml down
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

Проверка:

```bash
curl -I https://dev.usemycontent.ru/
```

Дальше используйте обычный запуск с dev-конфигом:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```
