# KAPA BANK — COMPLETE SYSTEM EXPLANATION & ARCHITECTURE GUIDE
**Bank Transaction Management System | Academic & Technical Viva Reference**

---

## 1. Executive Summary & Project Purpose

**KAPA Bank** is an enterprise-grade Bank Transaction Management System engineered to demonstrate core **Database Management System (DBMS)** principles within an authentic financial setting.

Rather than relying on simplified embedded databases (like SQLite) or high-level Object-Relational Mappings (ORMs) that hide SQL internals, KAPA Bank uses explicit, parameterized SQL connected directly to an **Oracle Autonomous Cloud Database (ATP)**.

### Core Academic Goals
1. **ACID Properties** (Atomicity, Consistency, Isolation, Durability) in production.
2. **Concurrency Control & Row-Level Locking** (`SELECT ... FOR UPDATE`) to prevent double-spending and lost updates.
3. **Deadlock Prevention** using ordered resource acquisition (min-then-max account locking).
4. **Role-Based Access Control (RBAC)** providing strict isolation between Administrator functions and individual Customer portals.
5. **Modern Full-Stack Engineering** featuring accessible UI/UX, serverless Python microservices, and mutual TLS (mTLS) cloud wallet security.

---

## 2. High-Level Architecture

The system operates across three tiers: a client presentation tier, a serverless application tier, and an enterprise cloud database tier.

```
                          ┌───────────────────────────┐
                          │   Client / Web Browser    │
                          └─────────────┬─────────────┘
                                        │ HTTPS
                                        ▼
                          ┌───────────────────────────┐
                          │     Vercel Edge / WSGI    │
                          │      (Serverless Flask)   │
                          └─────────────┬─────────────┘
                                        │
             ┌──────────────────────────┴──────────────────────────┐
             │                                                     │
             ▼                                                     ▼
┌───────────────────────────┐                         ┌───────────────────────────┐
│     Frontend Layer        │                         │      Backend Layer        │
│ • Jinja2 HTML5 Templates  │                         │ • Flask (Python 3.12/14)  │
│ • Custom Vanilla CSS      │ ◄────────────────────── │ • Session Management      │
│ • Responsive & Accessible │   Context / Variables   │ • Route Handlers & RBAC   │
│ • Modern SVG / No Bloat   │                         │ • Transaction Controller  │
└───────────────────────────┘                         └─────────────┬─────────────┘
                                                                    │
                                                                    │ python-oracledb (Thin Mode)
                                                                    │ mTLS Cloud Wallet (SSL)
                                                                    ▼
                                                      ┌───────────────────────────┐
                                                      │   Oracle Autonomous DB    │
                                                      │ • 6 Relational Tables     │
                                                      │ • Check & Integrity Rules │
                                                      │ • Pessimistic Locks       │
                                                      │ • Savepoints & Rollbacks  │
                                                      └───────────────────────────┘
```

---

## 3. Database Layer (Oracle Autonomous Cloud DB)

The database engine is hosted on Oracle Cloud Infrastructure (OCI) running Oracle Autonomous Transaction Processing (ATP) in the cloud.

### The 6 Relational Tables

| Table Name | Description | Key Constraints & Integrity Rules |
|---|---|---|
| `CUSTOMERS` | Stores customer identity and personal contact records. | `PK: customer_id`, `UQ: email`, `UQ: phone` |
| `USERS` | Authentication credentials, encrypted passwords, and RBAC roles. | `PK: user_id`, `FK: customer_id`, `UQ: email`, `CHK: role IN ('ADMIN', 'CUSTOMER')` |
| `BANK_ACCOUNTS` | Deposit and current accounts with real-time balances. | `PK: account_id`, `FK: customer_id`, `UQ: account_number`, `CHK: balance >= 0`, `CHK: status IN ('ACTIVE', 'FROZEN')` |
| `BANK_TRANSACTIONS` | Immutable double-entry transaction ledger. | `PK: transaction_id`, `FK: account_id`, `CHK: amount > 0`, `CHK: status IN ('COMMITTED', 'ROLLED_BACK', 'FAILED')` |
| `BANK_TRANSFERS` | Inter-account payment audit entries. | `PK: transfer_id`, `FK: from_account`, `FK: to_account`, `CHK: amount > 0`, `CHK: from_account <> to_account` |
| `AUDIT_LOG` | Security audit trail recording system actions. | `PK: audit_id`, `FK: user_id`, `timestamp` |

### Database Design & DBMS Mechanics

1. **Third Normal Form (3NF) & BCNF**:
   * Customer identity is kept strictly separate from login credentials (`CUSTOMERS` vs `USERS`).
   * Financial account data is isolated from ledger records (`BANK_ACCOUNTS` vs `BANK_TRANSACTIONS`).
   * All non-key attributes are fully and non-transitively dependent on the primary key.

2. **Pessimistic Row-Level Locking (`SELECT ... FOR UPDATE`)**:
   * During any financial transaction (deposit, withdrawal, or transfer), the backend issues:
     ```sql
     SELECT balance, status FROM bank_accounts WHERE account_id = :id FOR UPDATE;
     ```
   * This locks the row in the Oracle buffer cache until an explicit `COMMIT` or `ROLLBACK` is issued. Any concurrent request attempting to access that account must wait, preventing lost updates and race conditions.

3. **Deadlock Prevention Algorithm**:
   * When transferring funds between two accounts ($A$ and $B$), a circular wait deadlock could occur if two transfers execute simultaneously in opposite directions.
   * **Solution**: The backend always acquires row locks in deterministic ascending numerical order:
     ```python
     first_lock = min(from_account_id, to_account_id)
     second_lock = max(from_account_id, to_account_id)
     ```
   * Because all transactions acquire locks in identical global order, circular wait is mathematically impossible.

4. **Database Check Constraints as Invariant Guards**:
   * The constraint `CHECK (balance >= 0)` guarantees that no account can drop into a negative balance at the storage engine level.
   * The constraint `CHECK (from_account <> to_account)` prevents self-transfer circularities.

5. **Savepoints & Partial Rollbacks**:
   * Demonstrates fine-grained transaction control on `/transaction-control`:
     ```sql
     UPDATE bank_accounts SET balance = balance + 1000 WHERE account_id = 21;
     SAVEPOINT sp1;
     UPDATE bank_accounts SET balance = balance + 2000 WHERE account_id = 21;
     ROLLBACK TO SAVEPOINT sp1;
     COMMIT;
     ```
   * Result: The second operation is discarded while the first operation is permanently committed.

---

## 4. Backend Layer (Python & Flask)

The backend is built in Python using Flask, structured into modular files for connection management, security, and route handling.

### Key Modules

1. **`database.py` (Oracle Connection & Wallet Orchestration)**:
   * Uses `python-oracledb` in **Thin Mode**, eliminating the need for heavy C libraries (`libclntsh.so`) and enabling seamless deployment in serverless containers.
   * Dynamically constructs the Oracle Cloud Wallet files (`cwallet.sso`, `tnsnames.ora`) into `/tmp/wallet` when running inside serverless environments (e.g., Vercel).
   * Implements `dictfetchall(cursor)` and `dictfetchone(cursor)` helpers to transform raw Oracle tuples into clean Python dictionaries keyed by lowercase column names.

2. **`auth.py` & Security Middleware**:
   * Implements secure password hashing using `werkzeug.security` (PBKDF2 with SHA-256 and unique per-user salt).
   * Enforces Role-Based Access Control (RBAC) through reusable decorators:
     * `@login_required`: Guards authenticated pages.
     * `@admin_required`: Restricts administrative routes to users with `role == 'ADMIN'`.
     * `@customer_required`: Protects personal customer views.

3. **Dual Application Portals in `app.py`**:
   * **Admin Portal** (`/admin`, `/customers`, `/accounts`, `/reports`, `/transaction-control`):
     * Allows bank staff to search and view all customers, freeze or activate accounts, inspect audit trails, and run the ACID transaction control lab.
   * **Customer Portal** (`/portal`, `/portal/transfer`, `/portal/statement`):
     * Strictly isolates user data: Customers can only query accounts, view transactions, and initiate transfers that belong directly to their own `customer_id`.
     * Generates downloadable PDF statements dynamically using Python's `reportlab` library.

---

## 5. Frontend Layer (HTML5, Jinja2, Modern Vanilla CSS)

The user interface was built to provide a modern fintech user experience without relying on heavy frontend frameworks.

1. **Semantic HTML5 & Jinja2 Templates**:
   * Server-rendered templates (`base.html`, `login.html`, `portal.html`, `admin_dashboard.html`, etc.) ensure fast load times and clean separation of concerns.
   * Structured data presentation: Financial ledgers use semantic `<table>`, `<caption>`, and `<th scope="col">` elements.

2. **Accessibility Standards (WCAG 2.2 AA)**:
   * Contrast ratios meet or exceed 4.5:1 for normal text.
   * Every form input has an associated, explicit `<label for="...">`.
   * High-visibility `:focus-visible` states for keyboard navigation.
   * Decorative SVG icons are marked with `aria-hidden="true"`.

3. **Modern Vanilla CSS (`static/style.css` & `public/style.css`)**:
   * Built entirely from scratch with no external CSS framework dependencies (no Bootstrap or Tailwind overhead).
   * Responsive layout with CSS Grid and Flexbox adapting across mobile, tablet, and desktop viewports.
   * Interactive components including password visibility toggles (eye icons) and live Quick Evaluation Credential modals.

---

## 6. Deployment & Cloud Infrastructure

The application runs on a dual-cloud architecture:

1. **Database Cloud**: **Oracle Cloud Infrastructure (OCI)**
   * Always Free Autonomous Database ATP 19c/23ai.
   * Features automated continuous backups, hardware-level encryption at rest, and encrypted mTLS transport.

2. **Web Application Cloud**: **Vercel Serverless Platform**
   * Configured via `vercel.json` routing HTTP traffic through `api/index.py`.
   * Integrated Git CI/CD: Commits pushed to GitHub trigger automated builds, dependency installation (`requirements.txt`), and zero-downtime deployments.

---

## 7. Security & Credentials Management

To ensure compliance with production security standards:
* **No plaintext passwords in source control**: All passwords in the database are stored as salted cryptographic hashes.
* **Environment Separation (`.env`)**: Real database passwords and wallet passphrases are stored in an untracked `.env` file (enforced by `.gitignore`). Only `.env.example` containing dummy placeholders is tracked in the repository.
* **Oracle Cloud Wallet**: Physical wallet files reside outside the repository directory on local environments, and are decoded from base64 environment variables in serverless production.
* **Quick Evaluation Modal**: Evaluator accounts shown on the login modal are queried dynamically from the database at runtime rather than being hardcoded into static templates.

---

## 8. Summary of Completed Engineering Milestones

1. **Database Architecture & Constraints**: Designed and implemented 6 normalized tables with relational integrity and check constraints.
2. **ACID & Concurrency Engine**: Built deterministic row-level locking (`SELECT ... FOR UPDATE`) and deadlock prevention for inter-account transfers.
3. **Multi-User Architecture & RBAC**: Implemented role separation between System Administrators and Bank Customers.
4. **Customer Self-Service Portal**: Developed an isolated customer dashboard, domestic transfer engine, and dynamic PDF statement generator.
5. **Interactive Transaction Lab**: Created the live `/transaction-control` interface demonstrating `COMMIT`, `ROLLBACK`, and `SAVEPOINT` mechanics.
6. **Frontend & Accessibility Polish**: Authored responsive CSS, form validation, and WCAG 2.2 AA compliant templates.
7. **Production Deployment & Cloud CI/CD**: Deployed to Vercel connected to Oracle Autonomous Cloud Database.

---

## 9. Viva Voce Defense Guide (Common Q&A)

### Q1: What is the core DBMS significance of this project?
> **Answer:** "The project demonstrates practical transaction management and concurrency control on an enterprise database engine (Oracle Autonomous Cloud DB). Rather than abstracting database operations through an ORM, it implements explicit SQL transactions, row-level locking with `SELECT ... FOR UPDATE`, deterministic deadlock prevention, and database-level integrity constraints to guarantee ACID properties in financial operations."

### Q2: Why didn't you use an ORM like SQLAlchemy?
> **Answer:** "An ORM was deliberately avoided to maintain strict, deterministic control over transaction boundaries, locking behavior, and SQL execution. In financial systems, explicit control over `COMMIT`, `ROLLBACK`, `SAVEPOINT`, and pessimistic lock acquisition is essential to demonstrate and verify DBMS principles."

### Q3: How does KAPA Bank prevent race conditions and lost updates during transfers?
> **Answer:** "When a transfer begins, both the sender and recipient account rows in `BANK_ACCOUNTS` are locked immediately using `SELECT ... FOR UPDATE`. Any concurrent request attempting to read or modify either account must wait until the current transaction completes with `COMMIT` or `ROLLBACK`."

### Q4: How do you prevent deadlocks during concurrent inter-account transfers?
> **Answer:** "We use an ordered resource acquisition strategy. When locking two accounts ($A$ and $B$), the system always locks $\min(A, B)$ first, followed by $\max(A, B)$. Because all concurrent transactions acquire locks in the exact same numerical order, a circular wait condition cannot occur, mathematically preventing deadlocks."

### Q5: How is data isolation maintained between customers?
> **Answer:** "Through Role-Based Access Control (RBAC). Customer session IDs are verified at the controller level, and all SQL queries in customer routes explicitly filter by `WHERE customer_id = :session_customer_id`. A customer cannot view, modify, or transfer funds from an account that does not belong to them."
