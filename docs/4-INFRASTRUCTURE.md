---
title: Infrastructure Overview
tags: [infrastructure, services, deployment]
aliases: [Infrastructure Overview]
---

# Infrastructure Overview

## Services & Technology Stack

### PostgreSQL 16 (Port 5432)
**Purpose:** Primary relational database with PostGIS extension

**Key Features:**
- 30+ tables with normalized schema
- Foreign key constraints for referential integrity
- Indexes on frequently queried columns
- JSONB support for flexible data

**Access Methods:**
- **Local:** `psql postgresql://user:password@localhost:5432/ugc`
- **Docker:** `docker exec ugc-db psql -U user -d ugc`
- **Dev Server:** Via PgBouncer on port 6432

**Migrations:**
- Managed by Alembic (64+ migrations)
- Run `make migrate` to apply

### PgBouncer (Port 6432)
**Purpose:** Connection pooling for PostgreSQL

**Config:** Session mode (required for Alembic compatibility)

**Used By:**
- All application instances
- Admin panel
- Background workers

### Redis (Port 6379)
**Purpose:** Caching, FSM state storage, rate limiting

**Data Structures:**
- `fsm:{user_id}` — aiogram FSM context
- `cache:*` — Application caches
- `rate_limit:*` — Request rate limiting

**Expiration:** FSM contexts auto-expire after conversation ends

### Kafka (Port 9092)
**Purpose:** Event bus for distributed consistency

**Pattern:** Outbox pattern
- Write to Outbox table in PostgreSQL
- Background worker (`outbox_processor.py`) publishes to Kafka
- Consumers (`kafka_consumer.py`) process events

**Topics:**
- `offer-events` — Offer created, accepted, completed
- `user-events` — User registered, profile updated
- `payment-events` — Payment processed

### Prometheus (Port 9090)
**Purpose:** Metrics collection

**Metrics Exported:**
- Request latency (histograms)
- Error rates (counters)
- Active users (gauges)
- Database connection pool stats

**Scrape Interval:** 15 seconds

### Grafana (Port 3000)
**Purpose:** Metrics visualization & dashboards

**Key Dashboards:**
- System health (CPU, memory, disk)
- Application metrics (requests, errors, latency)
- Database metrics (connections, query times)
- Bot activity (messages, users, offers)

### Loki (Port 3100)
**Purpose:** Log aggregation

**Log Sources:**
- Application logs (stdout)
- Nginx access logs
- Database logs

**Retention:** 30 days

### AlertManager (Port 9093)
**Purpose:** Alert routing and management

**Configured Alerts:**
- High error rate (>5% of requests)
- Database connection pool near capacity
- Redis connectivity issues
- Kafka producer failures

## Deployment Architecture

### Development
```
├─ Telegram Bot (polling mode)
├─ Redis (FSM state)
└─ PostgreSQL (local)
```

### Staging/Dev Server
```
Nginx (reverse proxy)
├─ Telegram Bot Webhook (port 9999)
├─ Instagram Webhook (port 8002)
├─ Admin Panel (port 8001)
├─ Mini App API (port 8000)
└─ Max Bot Webhook (port 8003)

Infrastructure:
├─ PostgreSQL 16 + PgBouncer
├─ Redis
├─ Kafka
├─ Monitoring Stack (Prometheus, Grafana, Loki, AlertManager)
└─ Backup service (pg_dump)
```

### Docker Compose Services

#### App Services
```yaml
telegram_bot_app:
  Entry point: telegram_webhook_app.py
  Port: 9999
  Environment: BOT_TOKEN, DATABASE_URL, REDIS_URL

instagram_webhook_app:
  Entry point: instagram_webhook_app.py
  Port: 8002
  Purpose: Instagram webhook receiver

admin_app:
  Entry point: admin/app.py
  Port: 8001
  Database: PostgreSQL (via PgBouncer)

miniapp_app:
  Entry point: miniapp/app.py
  Port: 8000
  Purpose: Telegram Mini App FastAPI server
```

#### Background Workers
```yaml
kafka_consumer:
  Entry point: kafka_consumer.py
  Purpose: Process events from Kafka topics

outbox_processor:
  Entry point: outbox_processor.py
  Purpose: Publish pending outbox entries to Kafka

feedback_scheduler:
  Entry point: feedback_scheduler.py
  Purpose: Send scheduled feedback reminders

role_reminder_scheduler:
  Entry point: role_reminder_scheduler.py
  Purpose: Send role-specific notifications
```

#### Infrastructure Services
```yaml
db:
  Image: postgres:16-alpine
  Port: 5432
  Volumes: pgdata:/var/lib/postgresql/data

redis:
  Image: redis:7-alpine
  Port: 6379

kafka:
  Image: confluent/kafka:7.6.1
  Port: 9092
  Broker: CONFLUENT_KAFKA_BROKERS=kafka:9092

zookeeper:
  Purpose: Kafka coordination
  Port: 2181

pgbouncer:
  Port: 6432
  Config: session mode

nginx:
  Port: 80, 443
  Purpose: Reverse proxy, SSL termination
```

#### Monitoring Stack
```yaml
prometheus:
  Port: 9090
  Config: config/monitoring/prometheus.yml
  Scrape targets: all services

grafana:
  Port: 3000
  Dashboards: config/monitoring/grafana/

loki:
  Port: 3100
  Purpose: Log aggregation

alertmanager:
  Port: 9093
  Rules: config/monitoring/alertmanager.yml
```

## Environment Variables

### Required for Telegram
```env
BOT_TOKEN=<from BotFather>
WEBHOOK_BASE_URL=https://yourdomain.com
WEBHOOK_SECRET=<random_secret>
ADMIN_PASSWORD=<admin_panel_password>
ADMIN_SECRET=<admin_panel_secret>
```

### Database
```env
DATABASE_URL=postgresql+psycopg://user:pass@pgbouncer:6432/ugc
REDIS_URL=redis://redis:6379
```

### Kafka
```env
KAFKA_BROKERS=kafka:9092
```

### Instagram (if enabled)
```env
INSTAGRAM_ACCESS_TOKEN=<from Meta>
INSTAGRAM_BUSINESS_ACCOUNT_ID=<your_business_id>
```

### Monitoring
```env
PROMETHEUS_ENABLED=true
GRAFANA_ADMIN_PASSWORD=<password>
LOKI_ENABLED=true
```

## Deployment Commands

### Local Development
```bash
make install-dev   # Install dependencies
make admin         # Start admin panel
python -m ugc_bot.app  # Start bot (polling)
```

### Docker Development
```bash
make dev-up        # Full dev stack
make dev-down      # Stop stack
docker-compose logs -f  # View logs
```

### Production Deployment
```bash
make deploy-apps   # Zero-downtime rolling deploy
# Updates app → waits for health → updates app_2
```

## Monitoring & Observability

### Health Checks
- `/health` endpoint — Application readiness
- Prometheus targets — Service availability
- Kafka brokers — Message bus status
- Redis PING — Cache availability

### Key Metrics to Watch
- **Request latency (p95):** <500ms
- **Error rate:** <1%
- **Database connections:** <80/max
- **Redis memory:** <80% of limit
- **Kafka lag:** <10 seconds

### Common Issues

| Issue | Symptom | Solution |
|-------|---------|----------|
| **DB Connection Pool Exhausted** | 504 errors | Restart app service |
| **Redis OOM** | Cache misses | Increase Redis memory or enable eviction |
| **Kafka Producer Lag** | Events delayed | Check Kafka broker health |
| **High Request Latency** | Timeouts | Check database slow queries |

---

## Related Documents
- [[Architecture Overview]]
- [[Development Workflow]]
- [[Backup & Replication]]
