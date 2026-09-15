# KAPA BANK — TRADITIONAL ER MODEL (CHEN'S NOTATION)
**Bank Transaction Management System | Academic Database Specification**

---

## 1. Traditional ER Symbols Reference Key

This model follows standard academic **Peter Chen Notation** conforming strictly to the official database curriculum:

| Figure Name | Graphical Symbol | Semantic Meaning in Model |
|---|:---:|---|
| **Rectangle** | `[ ENTITY ]` | **Strong Entity Set** (Has independent existence and its own primary key). |
| **Double Rectangle** | `[[ WEAK ENTITY ]]` | **Weak Entity Set** (Existence-dependent on an owner entity; cannot exist without parent). |
| **Ellipse** | `( Attribute )` | **Attribute** of an entity or relationship. |
| **Underlined Ellipse** | `(_Key Attribute_)` | **Primary Key / Key Attribute** that uniquely identifies an entity instance. |
| **Double Ellipse** | `(( Multivalued ))` | **Multivalued Attribute** (can hold multiple values for an entity instance). |
| **Diamond** | `< RELATIONSHIP >` | **Relationship Set** connecting two or more entities. |
| **Double Diamond** | `<< IDENTIFYING REL >>` | **Identifying Relationship** connecting a Weak Entity to its Owner Entity. |
| **Single Line** | `───────` | **Partial Participation** (Entities may or may not participate in the relationship). |
| **Double Line** | `═══════` | **Total Participation** (Every entity instance must participate in the relationship). |

---

## 2. Complete Traditional ER Diagram (ASCII Representation)

```
                     ( name )           (_customer_id_)
                         \                  /
              ( phone )───[  CUSTOMERS  ]───( email )
                         /      │       \
                   ( address )  │        ( created_at )
                                │ 1 [Partial]
                                │
                             < OWNS >
                                ║
                                ║ M [Total Participation: Every account must have a customer]
                                ║
     ( account_number )        ╔╩═════════════════╗
            │                  ║  BANK_ACCOUNTS   ║════< HAS_ENTRY >════╔═════════════════════╗
        ( balance )────────────║  (Weak Entity)   ║                     ║  BANK_TRANSACTIONS  ║
            │                  ╚╦═════════════════╝                     ║    (Weak Entity)    ║
        ( status )              ║        │                              ╚══════════╦══════════╝
                                ║        ├──( account_type )                       ║
                                ║        └──( created_date )                       ║ M [Total]
                                ║ 1 [Partial]                                      ║
                                ║                                                  ║
                        < SENDS_TRANSFER >                                         ║
                                ║                                                  ║
                                ║ M [Total]                                        ║
                                ║                                                  ║
                       ╔════════╩═════════╗                                        ║
                       ║  BANK_TRANSFERS  ║                                        ║
                       ║  (Weak Entity)   ║                                        ║
                       ╚════════╦═════════╝                                        ║
                         /      ║       \                                          ║
         (_transfer_id_)        ║        ( transfer_date )                         ║
                │               ║ 1 [Partial]                                      ║
            ( amount )───< RECEIVES_TRF >                                          ║
                │                                                                  ║
            ( status )                                                             ║
                                                                                   ║
                                                                                   ║
                          [   USERS   ]                                            ║
                         /      │      \                                           ║
              ( role )──+       │       +──(_user_id_)                             ║
             ( email )──+       │       +──( password_hash )                       ║
        ( display_pwd )─+       │       +──( is_active )                           ║
                                │       +──( created_at )                          ║
                                │ 1 [Partial]                                      ║
                                │                                                  ║
                             < LOGS >                                              ║
                                ║                                                  ║
                                ║ M [Total: Every audit entry must be logged]      ║
                                ║                                                  ║
                       ╔════════╩═════════╗                                        ║
                       ║    AUDIT_LOG     ║                                        ║
                       ║  (Weak Entity)   ║                                        ║
                       ╚════════╦═════════╝                                        ║
                         /      │       \                                          ║
             (_audit_id_)       │        ( timestamp )                             ║
                 │              +──( ip_address )                                  ║
             ( action )         └──( entity_type, entity_id, details )             ║
                                                                                   ║
            ═══════════════════════════════════════════════════════════════════════╝
            ║
            v
     Detailed Attributes of BANK_TRANSACTIONS:
            ├── (_transaction_id_)   [Key Attribute]
            ├── ( transaction_type ) [DEPOSIT, WITHDRAWAL, TRANSFER_IN, TRANSFER_OUT]
            ├── ( amount )           [CHECK: amount > 0]
            ├── ( transaction_date ) [Timestamp]
            └── ( status )           [COMMITTED, ROLLED_BACK, FAILED]
```

---

## 3. Entities, Attributes & Key Classifications

### 1. `CUSTOMERS`
* **Entity Type:** Strong Entity `[ CUSTOMERS ]` (Single Rectangle).
* **Primary Key:** `customer_id` (Underlined Ellipse: `(_customer_id_)`).
* **Candidate Keys:** `email`, `phone`.
* **Attributes (Ellipses):**
  * `(_customer_id_)` — Key attribute, Simple, Single-valued.
  * `( name )` — Composite/Simple, Single-valued.
  * `( email )` — Simple, Single-valued, Unique.
  * `( phone )` — Simple, Single-valued, Unique.
  * `( address )` — Simple, Single-valued, Nullable.
  * `( created_at )` — Simple, Temporal attribute.
* **Participation in Relationships:**
  * `< OWNS >`: **Partial Participation** (A registered customer might not have opened an account yet).
  * `< AUTHENTICATES >`: **Partial Participation** (A customer may not have web login credentials enabled).

---

### 2. `BANK_ACCOUNTS`
* **Entity Type:** Weak Entity `[[ BANK_ACCOUNTS ]]` (Double Rectangle) — existence-dependent on `CUSTOMERS`.
* **Primary Key:** `account_id` (Underlined Ellipse: `(_account_id_)`).
* **Candidate Key:** `account_number` (Unique alphanumeric account code).
* **Attributes (Ellipses):**
  * `(_account_id_)` — Key attribute.
  * `( account_number )` — Simple, Single-valued, Unique.
  * `( account_type )` — Simple, Domain: `{'SAVINGS', 'CURRENT'}`.
  * `( balance )` — Simple, Single-valued, Constrained: `balance >= 0`.
  * `( status )` — Simple, Domain: `{'ACTIVE', 'FROZEN'}`.
  * `( created_date )` — Simple, Temporal.
* **Participation in Relationships:**
  * `< OWNS >`: **Total Participation** (Double line: Every account **must** belong to a customer).
  * `< HAS_ENTRY >`: **Partial Participation** (A brand-new account might have 0 transactions initially).
  * `< SENDS_TRANSFER >`: **Partial Participation** (An account may or may not initiate transfers).
  * `< RECEIVES_TRF >`: **Partial Participation** (An account may or may not receive transfers).

---

### 3. `BANK_TRANSACTIONS`
* **Entity Type:** Weak Entity `[[ BANK_TRANSACTIONS ]]` (Double Rectangle) — existence-dependent on `BANK_ACCOUNTS`.
* **Primary Key:** `transaction_id` (Underlined Ellipse: `(_transaction_id_)`).
* **Attributes (Ellipses):**
  * `(_transaction_id_)` — Key attribute.
  * `( transaction_type )` — Domain: `{'DEPOSIT', 'WITHDRAWAL', 'TRANSFER_IN', 'TRANSFER_OUT'}`.
  * `( amount )` — Simple, Constrained: `amount > 0`.
  * `( transaction_date )` — Simple, Temporal timestamp.
  * `( status )` — Domain: `{'COMMITTED', 'ROLLED_BACK', 'FAILED'}`.
* **Participation in Relationships:**
  * `< HAS_ENTRY >`: **Total Participation** (Double line: Every transaction entry must be tied to a bank account).

---

### 4. `BANK_TRANSFERS`
* **Entity Type:** Weak / Associative Entity `[[ BANK_TRANSFERS ]]` (Double Rectangle).
* **Primary Key:** `transfer_id` (Underlined Ellipse: `(_transfer_id_)`).
* **Attributes (Ellipses):**
  * `(_transfer_id_)` — Key attribute.
  * `( amount )` — Simple, Constrained: `amount > 0`.
  * `( transfer_date )` — Simple, Temporal.
  * `( status )` — Domain: `{'COMMITTED', 'ROLLED_BACK', 'FAILED'}`.
* **Participation in Relationships:**
  * `< SENDS_TRANSFER >`: **Total Participation** (Every transfer record must have a source account).
  * `< RECEIVES_TRF >`: **Total Participation** (Every transfer record must have a destination account).
  * **Integrity Constraint:** `from_account <> to_account` (Anti-reflexive transfer rule).

---

### 5. `USERS`
* **Entity Type:** Strong Entity `[ USERS ]` (Single Rectangle).
* **Primary Key:** `user_id` (Underlined Ellipse: `(_user_id_)`).
* **Attributes (Ellipses):**
  * `(_user_id_)` — Key attribute.
  * `( email )` — Simple, Unique login username.
  * `( password_hash )` — Cryptographic hash string (PBKDF2/SHA-256).
  * `( display_password )` — Plaintext helper for academic viva evaluation.
  * `( role )` — Domain: `{'ADMIN', 'CUSTOMER'}`.
  * `( is_active )` — Domain: `{0, 1}`.
  * `( created_at )` — Simple, Temporal.
* **Participation in Relationships:**
  * `< AUTHENTICATES >`: **Partial Participation** (1 : 1 optional: an Admin user does not map to a customer).
  * `< LOGS >`: **Partial Participation** (A user may exist without yet triggering audited security actions).

---

### 6. `AUDIT_LOG`
* **Entity Type:** Weak Entity `[[ AUDIT_LOG ]]` (Double Rectangle).
* **Primary Key:** `audit_id` (Underlined Ellipse: `(_audit_id_)`).
* **Attributes (Ellipses):**
  * `(_audit_id_)` — Key attribute.
  * `( action )` — Action descriptor (`LOGIN_SUCCESS`, `TRANSFER_EXECUTED`, etc.).
  * `( entity_type )` — Target table (`BANK_ACCOUNTS`, `USERS`, etc.).
  * `( entity_id )` — Numeric ID of the modified entity.
  * `( details )` — Operational context string.
  * `( ip_address )` — Remote client IP.
  * `( timestamp )` — Precise system audit timestamp.
* **Participation in Relationships:**
  * `< LOGS >`: **Total Participation** (Double line: An audit log record cannot exist without an actor/user).

---

## 4. Relationship Sets, Cardinality & Participation Matrix

| Relationship Name | Symbol | Entity 1 | Entity 2 | Cardinality Ratio ($E_1 : E_2$) | Participation $E_1$ | Participation $E_2$ |
|---|:---:|---|---|:---:|:---:|:---:|
| `< OWNS >` | Diamond $\Diamond$ | `CUSTOMERS` | `BANK_ACCOUNTS` | $1 : N$ | Partial (Single Line) | **Total (Double Line)** |
| `< AUTHENTICATES >` | Diamond $\Diamond$ | `CUSTOMERS` | `USERS` | $1 : 1$ | Partial (Single Line) | Partial (Single Line) |
| `< HAS_ENTRY >` | Diamond $\Diamond$ | `BANK_ACCOUNTS` | `BANK_TRANSACTIONS` | $1 : N$ | Partial (Single Line) | **Total (Double Line)** |
| `< SENDS_TRANSFER >` | Diamond $\Diamond$ | `BANK_ACCOUNTS` | `BANK_TRANSFERS` | $1 : N$ | Partial (Single Line) | **Total (Double Line)** |
| `< RECEIVES_TRF >` | Diamond $\Diamond$ | `BANK_ACCOUNTS` | `BANK_TRANSFERS` | $1 : N$ | Partial (Single Line) | **Total (Double Line)** |
| `< LOGS >` | Diamond $\Diamond$ | `USERS` | `AUDIT_LOG` | $1 : N$ | Partial (Single Line) | **Total (Double Line)** |

---

## 5. ER to Relational Mapping Rules (Academic Defense Proof)

When converting this Traditional ER Model into the SQL Relational Schema, the standard 7-step mapping algorithm is applied:

1. **Mapping of Strong Entities (`CUSTOMERS`, `USERS`)**:
   * Create table for each strong entity.
   * Underlined key attribute becomes SQL `PRIMARY KEY`.
   * `CUSTOMERS(customer_id, name, email, phone, address, created_at)`
   * `USERS(user_id, email, password_hash, display_password, role, is_active, created_at)`

2. **Mapping of Weak Entities (`BANK_ACCOUNTS`, `BANK_TRANSACTIONS`, `AUDIT_LOG`)**:
   * Include all attributes of the weak entity.
   * Include the Primary Key of the owner entity as a `FOREIGN KEY`.
   * `BANK_ACCOUNTS(account_id, customer_id*, account_number, account_type, balance, status, created_date)`
   * `BANK_TRANSACTIONS(transaction_id, account_id*, transaction_type, amount, transaction_date, status)`
   * `AUDIT_LOG(audit_id, user_id*, action, entity_type, entity_id, details, ip_address, timestamp)`

3. **Mapping of 1:1 Binary Relationships (`< AUTHENTICATES >`)**:
   * Foreign Key approach: Add `customer_id` into `USERS` with `UNIQUE` constraint (or nullable foreign key) to allow pure Administrators.

4. **Mapping of 1:N Binary Relationships (`< OWNS >`, `< HAS_ENTRY >`, `< LOGS >`)**:
   * Post the primary key of the "1" side as a `FOREIGN KEY` on the "N" (many) side.

5. **Mapping of Recursive / Multi-Role Relationships (`< SENDS_TRANSFER >`, `< RECEIVES_TRF >`)**:
   * `BANK_TRANSFERS` receives two distinct foreign keys pointing back to `BANK_ACCOUNTS`:
     * `from_account REFERENCES bank_accounts(account_id)`
     * `to_account REFERENCES bank_accounts(account_id)`
   * Table constraint enforced: `CHECK (from_account <> to_account)`.
