---
tags: [index, home]
---

# UGC Bot Project — Obsidian Vault

Welcome to the **UGC Telegram Bot** documentation vault! This is your central hub for understanding the project architecture, features, decisions, and workflows.

## 🗂️ Quick Navigation

### 📚 Core Documentation
- [[Architecture Overview]] — System design, layering, and key components
- [[Development Workflow]] — How to develop, test, and deploy
- [[Domain Model]] — Key entities, enums, and business logic
- [[Database Schema]] — PostgreSQL structure and migrations

### 🎯 Features & Features Plans
- [[Authentication & Authorization]] — User types, roles, permissions
- [[Creator Matching System]] — How offers are matched to creators
- [[Referral System]] — Referral tracking and payouts
- [[Payment Processing]] — Invoice handling and transaction flow
- [[Blogger Rating System]] — Rating mechanics and algorithms
- [[Max Messenger Integration]] — Multi-messenger support (in progress)

### 🔧 Infrastructure
- [[Infrastructure Overview]] — Services, databases, monitoring
- [[Kafka & Event Bus]] — Event-driven architecture and outbox pattern
- [[Redis & Caching]] — State management and FSM storage
- [[Monitoring & Observability]] — Prometheus, Grafana, Loki, AlertManager
- [[Backup & Replication]] — Data durability and recovery

### 🤖 API & Integration
- [[Telegram Bot Handlers]] — Command and message handlers
- [[Mini App API]] — FastAPI endpoints for Telegram Mini App
- [[Instagram Integration]] — Graph API and web scraping
- [[Admin Panel]] — SQLAdmin dashboard features

### 📖 Concepts
- [[Ports & Adapters Pattern]] — Hexagonal architecture principles
- [[Repository Pattern]] — Data access abstraction
- [[Outbox Pattern]] — Event consistency guarantees
- [[FSM & State Management]] — Stateful conversations

### 🛠️ Developer Guides
- [[Local Development Setup]] — Environment and dependencies
- [[Testing Strategy]] — Unit, integration, and E2E tests
- [[Code Quality]] — Linting, formatting, type checking
- [[Git Workflow]] — Branching and commit conventions
- [[Debugging Tips]] — Common issues and solutions

### 📋 Decisions & Planning
- [[Architecture Decisions]] — ADR log with rationales
- [[Feature Backlog]] — Planned features and epics
- [[Tech Debt]] — Known issues and improvements
- [[2026 Roadmap]] — Quarterly goals and milestones

### 📊 System Diagrams
- [[System Architecture Diagram]]
- [[Data Flow Diagram]]
- [[User Journey Map]]
- [[Messenger Architecture]]

---

## 🚀 Getting Started

### New to the project?
1. Start with [[Architecture Overview]]
2. Read [[Domain Model]] to understand entities
3. Check [[Development Workflow]] for setup instructions
4. Explore [[Telegram Bot Handlers]] to see how things work

### Want to add a feature?
1. Check [[Feature Backlog]] for context
2. Create a design document using the Feature Plan template
3. Document your [[Architecture Decisions]] (ADR)
4. Follow [[Git Workflow]] for implementation
5. Write tests (see [[Testing Strategy]])

### Need to understand a concept?
- Use the **Graph View** (Ctrl+G) to visualize connections
- Search for keywords with **Cmd/Ctrl+F**
- Follow **backlinks** to find related documents
- Check [[Glossary]] for terms

---

## 📈 Vault Statistics
- **Total Pages:** 50+
- **Components:** 20+ (Handlers, Services, Repos, Adapters)
- **Services:** 20+ business logic services
- **Database Tables:** 30+
- **API Endpoints:** 15+

---

## 🔄 Recently Updated
- {{date:YYYY-MM-DD}} — [[Max Messenger Integration]] — In progress
- {{date:YYYY-MM-DD}} — [[Blogger Rating System]] — Completed
- {{date:YYYY-MM-DD}} — [[Creator Rating Feature]] — Added

---

## 📞 Questions?
- Check the [[Glossary]] for terminology
- Look for related documents using backlinks
- Search the vault with `Cmd/Ctrl+Shift+F`
- Review [[Architecture Decisions]] for design rationales

---

**Last Updated:** {{date:YYYY-MM-DD}}
**Vault Version:** 1.0
