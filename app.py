"""
KAPA Bank — Multi-User Bank Transaction Management System
Full-stack Flask application integrating Oracle Autonomous Database,
role-based access control, customer data isolation, audit logging,
ACID transaction demonstrations, and PDF statement generation.
"""
import os
import re
import secrets
import logging
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, make_response, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

import oracledb
from database import get_connection, dictfetchall, dictfetchone
from auth import (
    login_required, admin_required, customer_required,
    generate_csrf_token, validate_csrf, log_audit, get_current_user
)
from reports import generate_pdf_statement, generate_csv_statement

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "kapa-bank-secret-key-production-2026-vit")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=3600 # 1 hour
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEMO_ACCOUNT_ID = 21


# ============================================================
# CONTEXT PROCESSORS & TEMPLATE HELPERS
# ============================================================

@app.context_processor
def inject_global_template_context():
    """Provides CSRF token, authenticated user info, and helpers to all templates."""
    return {
        "csrf_token": generate_csrf_token,
        "current_user": get_current_user(),
        "now_year": 2026
    }


@app.after_request
def add_security_and_academic_headers(response):
    """Signals to web crawlers, security bots, and browsers that this is an educational project."""
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    response.headers["X-Academic-Project"] = "VIT DBMS Student Coursework - NOT A REAL BANK"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


# ============================================================
# HELPER VALIDATION & RESPONSE FUNCTIONS
# ============================================================

def validate_required(value, field_name):
    if not value or not str(value).strip():
        return f"{field_name} is required."
    return None

def validate_positive_amount(value):
    try:
        amount = Decimal(str(value).strip())
        if amount <= Decimal('0'):
            return None, "Amount must be strictly positive (greater than 0)."
        if amount.as_tuple().exponent < -2:
            return None, "Amount cannot have more than 2 decimal places."
        return amount, None
    except (InvalidOperation, ValueError, TypeError):
        return None, "Invalid currency amount format."

def safe_error_message(e):
    logger.error("Database operation error: %s", str(e), exc_info=True)
    error_msg = str(e)
    if "UQ_CUSTOMER_EMAIL" in error_msg or "UQ_USER_EMAIL" in error_msg:
        return "An account with this email address already exists."
    if "UQ_CUSTOMER_PHONE" in error_msg:
        return "A customer with this phone number already exists."
    if "UQ_ACCOUNT_NUMBER" in error_msg:
        return "An account with this account number already exists."
    if "CHK_DIFFERENT_ACCOUNTS" in error_msg:
        return "Source and destination accounts must be strictly different."
    if "CHK_ACCOUNT_BALANCE" in error_msg:
        return "Operation rejected: Account balance cannot drop below zero."
    return "An unexpected database error occurred. The transaction was safely rolled back."

def render_success(title, message, **kwargs):
    kwargs.setdefault('transaction_demo', False)
    kwargs.setdefault('back_url', '/')
    kwargs.setdefault('back_label', 'Return to Dashboard')
    kwargs.setdefault('transaction_status', 'COMMITTED')
    return render_template("success.html", title=title, message=message, **kwargs)

def render_error(title, message, back_url='/', back_label='Return to Dashboard'):
    return render_template("error.html", title=title, message=message, back_url=back_url, back_label=back_label)


def get_evaluation_credentials():
    """Fetches real-time demo/evaluation credentials from the database for display on login and credentials directory."""
    creds = {
        'admin': {'email': 'admin@kapabank.com', 'password': 'Admin@Kapa2026', 'role': 'ADMIN', 'customer_name': 'System Administrator'},
        'demo': {'email': 'demo@kapabank.com', 'password': 'Demoacc@123', 'role': 'CUSTOMER', 'customer_id': 21, 'customer_name': 'Demo Customer', 'accounts': 'DEMO1001'},
        'rahul': {'email': 'rahul@example.com', 'password': 'Customer@123', 'role': 'CUSTOMER', 'customer_id': 1, 'customer_name': 'Rahul Kumar', 'accounts': 'KAPA1001, KAPA1002'},
        'kanishka': {'email': 'kanishka.jayakumar2025@vitstudent.ac.in', 'password': 'Customer@123', 'role': 'CUSTOMER', 'customer_id': 2, 'customer_name': 'Kanishka', 'accounts': 'KAPA2001'},
        'all_users': []
    }
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute("""
            SELECT 
                u.user_id,
                LOWER(u.email) AS email,
                u.display_password AS password,
                u.role,
                u.customer_id,
                c.name AS customer_name,
                (SELECT LISTAGG(account_number, ', ') WITHIN GROUP (ORDER BY account_id)
                 FROM bank_accounts WHERE customer_id = u.customer_id) AS accounts
            FROM users u
            LEFT JOIN customers c ON u.customer_id = c.customer_id
            WHERE u.display_password IS NOT NULL
            ORDER BY 
                CASE WHEN u.role = 'ADMIN' THEN 1
                     WHEN u.customer_id = 21 THEN 2
                     ELSE 3 END,
                u.user_id ASC
        """)
        rows = dictfetchall(cursor)
        for r in rows:
            if r.get('role') == 'ADMIN' and not r.get('customer_name'):
                r['customer_name'] = 'System Administrator'
        creds['all_users'] = rows
        for r in rows:
            em = r['email']
            pwd = r.get('password')
            if not pwd:
                continue
            if em == 'admin@kapabank.com':
                creds['admin']['password'] = pwd
                creds['admin']['customer_name'] = r.get('customer_name')
            elif em == 'demo@kapabank.com':
                creds['demo']['password'] = pwd
                creds['demo']['customer_name'] = r.get('customer_name')
                creds['demo']['accounts'] = r.get('accounts')
            elif em == 'rahul@example.com':
                creds['rahul']['password'] = pwd
                creds['rahul']['customer_name'] = r.get('customer_name')
                creds['rahul']['accounts'] = r.get('accounts')
            elif 'kanishka' in em:
                creds['kanishka']['password'] = pwd
                creds['kanishka']['customer_name'] = r.get('customer_name')
                creds['kanishka']['accounts'] = r.get('accounts')
        cursor.close()
        connection.close()
    except Exception as e:
        logger.warning("Could not fetch realtime evaluation credentials: %s", str(e))
    return creds


# ============================================================
# AUTHENTICATION & SESSION ROUTES
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        if session.get("role") == "ADMIN":
            return redirect(url_for("admin_dashboard"))
        if session.get("customer_id") == DEMO_ACCOUNT_ID or str(session.get("email", "")).lower() == "demo@kapabank.com":
            return redirect(url_for("transaction_control_page"))
        return redirect(url_for("customer_dashboard"))

    eval_creds = get_evaluation_credentials()

    if request.method == "GET":
        next_url = request.args.get("next", "")
        email = request.args.get("email", "").strip().lower()
        password = ""
        if email:
            for k, c in eval_creds.items():
                if c['email'].lower() == email:
                    password = c['password']
                    break
        return render_template("login.html", next_url=next_url, email=email, password=password, eval_creds=eval_creds)

    # POST Login
    if not validate_csrf():
        return render_error("Security Validation Failed", "Invalid CSRF token. Please refresh and try again.", "/login", "Back to Login")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    next_url = request.form.get("next_url", "").strip()

    if not email or not password:
        return render_template("login.html", error="Please provide both email and password.", email=email, next_url=next_url, eval_creds=eval_creds)

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            SELECT u.user_id, u.email, u.password_hash, u.role, u.customer_id, u.is_active,
                   c.name AS customer_name
            FROM users u
            LEFT JOIN customers c ON u.customer_id = c.customer_id
            WHERE LOWER(u.email) = :1
        """, (email,))
        user = dictfetchone(cursor)

        if not user or not check_password_hash(user['password_hash'], password):
            log_audit("LOGIN_FAILED", entity_type="USER", details=f"Failed login attempt for email: {email}")
            return render_template("login.html", error="Invalid email or password.", email=email, next_url=next_url, eval_creds=eval_creds)

        if user['is_active'] != 1:
            log_audit("LOGIN_BLOCKED", entity_type="USER", entity_id=user['user_id'], details="Inactive user login attempt", user_id=user['user_id'])
            return render_template("login.html", error="This user account has been disabled. Please contact administrator.", email=email, eval_creds=eval_creds)

        # Login successful — Establish Session
        session.clear()
        session["csrf_token"] = generate_csrf_token()
        session["user_id"] = user['user_id']
        session["email"] = user['email']
        session["role"] = user['role']
        session["customer_id"] = user['customer_id']
        session["user_name"] = user['customer_name'] if user['customer_name'] else ("Administrator" if user['role'] == "ADMIN" else "Customer")

        # Update last_login timestamp
        cursor.execute("UPDATE users SET last_login = SYSTIMESTAMP WHERE user_id = :1", (user['user_id'],))
        connection.commit()

        log_audit("LOGIN_SUCCESS", entity_type="USER", entity_id=user['user_id'], details=f"User logged in ({user['role']})", user_id=user['user_id'])

        if next_url and next_url.startswith("/"):
            return redirect(next_url)

        if user['role'] == "ADMIN":
            return redirect(url_for("admin_dashboard"))
        if user['customer_id'] == DEMO_ACCOUNT_ID or str(user['email']).lower() == "demo@kapabank.com":
            return redirect(url_for("transaction_control_page"))
        return redirect(url_for("customer_dashboard"))

    except Exception as e:
        logger.error("Login processing error: %s", str(e), exc_info=True)
        return render_template("login.html", error="A service error occurred. Please try again.", email=email, eval_creds=eval_creds)
    finally:
        cursor.close()
        connection.close()


@app.route("/logout")
def logout():
    uid = session.get("user_id")
    if uid:
        log_audit("LOGOUT", entity_type="USER", entity_id=uid, details="User logged out")
    session.clear()
    return redirect(url_for("login"))


@app.route("/credentials")
def demo_credentials():
    eval_creds = get_evaluation_credentials()
    return render_template("credentials.html", eval_creds=eval_creds)


@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("customer_dashboard"))

    if request.method == "GET":
        return render_template("register.html")

    # POST Registration
    if not validate_csrf():
        return render_error("Security Validation Failed", "Invalid CSRF token. Please refresh and try again.", "/register", "Back to Register")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    address = request.form.get("address", "").strip()
    password = request.form.get("password", "").strip()
    confirm_password = request.form.get("confirm_password", "").strip()
    account_type = request.form.get("account_type", "SAVINGS").strip()

    # Validations
    if err := validate_required(name, "Full Name"):
        return render_template("register.html", error=err, form=request.form)
    if err := validate_required(email, "Email Address"):
        return render_template("register.html", error=err, form=request.form)
    if err := validate_required(phone, "Phone Number"):
        return render_template("register.html", error=err, form=request.form)
    if len(password) < 6:
        return render_template("register.html", error="Password must be at least 6 characters long.", form=request.form)
    if password != confirm_password:
        return render_template("register.html", error="Passwords do not match.", form=request.form)
    if account_type not in ["SAVINGS", "CURRENT"]:
        account_type = "SAVINGS"

    connection = get_connection()
    cursor = connection.cursor()

    try:
        # Check if email is taken
        cursor.execute("SELECT user_id FROM users WHERE LOWER(email) = :1", (email,))
        if dictfetchone(cursor):
            return render_template("register.html", error="An account with this email address is already registered.", form=request.form)

        cursor.execute("SELECT customer_id FROM customers WHERE LOWER(email) = :1", (email,))
        if dictfetchone(cursor):
            return render_template("register.html", error="A customer with this email address already exists.", form=request.form)

        cursor.execute("SAVEPOINT before_registration")

        # 1. Insert Customer profile
        cursor.execute("""
            INSERT INTO customers (name, email, phone, address)
            VALUES (:1, :2, :3, :4)
        """, (name, email, phone, address))

        cursor.execute("SELECT customer_id FROM customers WHERE LOWER(email) = :1", (email,))
        cust_row = dictfetchone(cursor)
        new_customer_id = cust_row['customer_id']

        # 2. Insert User Authentication credentials
        pwd_hash = generate_password_hash(password)
        cursor.execute("""
            INSERT INTO users (email, password_hash, role, customer_id, is_active, display_password)
            VALUES (:1, :2, 'CUSTOMER', :3, 1, :4)
        """, (email, pwd_hash, new_customer_id, password))

        cursor.execute("SELECT user_id FROM users WHERE LOWER(email) = :1", (email,))
        new_user_id = dictfetchone(cursor)['user_id']

        # 3. Generate initial bank account number: ACC + 7 digits
        acc_num = f"ACC{secrets.randbelow(9000000) + 1000000}"
        cursor.execute("""
            INSERT INTO bank_accounts (customer_id, account_number, account_type, balance, status)
            VALUES (:1, :2, :3, 0, 'ACTIVE')
        """, (new_customer_id, acc_num, account_type))

        # 4. Audit Log
        cursor.execute("""
            INSERT INTO audit_log (user_id, action, entity_type, entity_id, details, ip_address)
            VALUES (:1, 'CUSTOMER_REGISTERED', 'CUSTOMER', :2, :3, :4)
        """, (new_user_id, new_customer_id, f"Self-registered with account {acc_num}", request.remote_addr or '127.0.0.1'))

        connection.commit()

        # Log the user in directly
        session.clear()
        session["csrf_token"] = generate_csrf_token()
        session["user_id"] = new_user_id
        session["email"] = email
        session["role"] = "CUSTOMER"
        session["customer_id"] = new_customer_id
        session["user_name"] = name

        return render_success(
            "Account Created Successfully!",
            f"Welcome to KAPA Bank, {name}. Your customer profile and {account_type} account ({acc_num}) have been opened.",
            back_url=url_for("customer_dashboard"),
            back_label="Go to My Dashboard"
        )

    except Exception as e:
        connection.rollback()
        return render_template("register.html", error=safe_error_message(e), form=request.form)
    finally:
        cursor.close()
        connection.close()


# ============================================================
# CUSTOMER PORTAL ROUTES (STRICT CUSTOMER DATA ISOLATION)
# ============================================================

@app.route("/")
def index():
    """Root entry point: redirects to Admin or Customer dashboard based on role."""
    if "user_id" not in session:
        return redirect(url_for("login"))
    if session.get("role") == "ADMIN":
        return redirect(url_for("admin_dashboard"))
    if session.get("customer_id") == DEMO_ACCOUNT_ID or str(session.get("email", "")).lower() == "demo@kapabank.com":
        return redirect(url_for("transaction_control_page"))
    return redirect(url_for("customer_dashboard"))


@app.route("/dashboard")
@customer_required
def customer_dashboard():
    if session.get("customer_id") == DEMO_ACCOUNT_ID or str(session.get("email", "")).lower() == "demo@kapabank.com":
        return redirect(url_for("transaction_control_page"))

    customer_id = session.get("customer_id")
    connection = get_connection()
    cursor = connection.cursor()

    try:
        # 1. Total Accounts owned by this customer
        cursor.execute("""
            SELECT COUNT(*) AS count 
            FROM bank_accounts 
            WHERE customer_id = :1
        """, (customer_id,))
        account_count = dictfetchone(cursor)['count']

        # 2. Total Balance across all active accounts owned by this customer
        cursor.execute("""
            SELECT NVL(SUM(balance), 0) AS total 
            FROM bank_accounts 
            WHERE customer_id = :1 AND status = 'ACTIVE'
        """, (customer_id,))
        total_balance = Decimal(str(dictfetchone(cursor)['total']))

        # 3. Total Transactions count for customer's accounts
        cursor.execute("""
            SELECT COUNT(t.transaction_id) AS count
            FROM bank_transactions t
            JOIN bank_accounts a ON t.account_id = a.account_id
            WHERE a.customer_id = :1
        """, (customer_id,))
        transaction_count = dictfetchone(cursor)['count']

        # 4. Customer's accounts summary
        cursor.execute("""
            SELECT account_id, account_number, account_type, balance, status, created_date
            FROM bank_accounts
            WHERE customer_id = :1
            ORDER BY account_id ASC
        """, (customer_id,))
        accounts = dictfetchall(cursor)

        # 5. Recent 5 Transactions for accounts owned by this customer
        cursor.execute("""
            SELECT 
                t.transaction_id, 
                t.account_id, 
                a.account_number, 
                t.transaction_type, 
                t.amount, 
                TO_CHAR(FROM_TZ(t.transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'DD-MM-YYYY') AS display_date,
                TO_CHAR(FROM_TZ(t.transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'HH12:MI AM') AS display_time,
                t.status
            FROM bank_transactions t
            JOIN bank_accounts a ON t.account_id = a.account_id
            WHERE a.customer_id = :1
            ORDER BY t.transaction_date DESC
            FETCH FIRST 5 ROWS ONLY
        """, (customer_id,))
        recent_transactions = dictfetchall(cursor)

    except Exception as e:
        logger.error("Customer dashboard error: %s", str(e), exc_info=True)
        return render_error("Dashboard Error", "Unable to load your dashboard data.", "/logout", "Log Out")
    finally:
        cursor.close()
        connection.close()

    return render_template(
        "customer/dashboard.html",
        account_count=account_count,
        total_balance=total_balance,
        transaction_count=transaction_count,
        accounts=accounts,
        recent_transactions=recent_transactions
    )


@app.route("/accounts")
@customer_required
def customer_accounts():
    customer_id = session.get("customer_id")
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            SELECT account_id, customer_id, account_number, account_type, balance, status, created_date
            FROM bank_accounts
            WHERE customer_id = :1
            ORDER BY created_date DESC
        """, (customer_id,))
        accounts_list = dictfetchall(cursor)
    except Exception as e:
        logger.error("Customer accounts error: %s", str(e), exc_info=True)
        accounts_list = []
    finally:
        cursor.close()
        connection.close()

    return render_template("customer/accounts.html", accounts=accounts_list)


@app.route("/accounts/<int:account_id>")
@customer_required
def customer_account_detail(account_id):
    customer_id = session.get("customer_id")
    connection = get_connection()
    cursor = connection.cursor()

    try:
        # STRICT BACKEND ISOLATION: verify account ownership
        cursor.execute("""
            SELECT a.account_id, a.customer_id, c.name AS customer_name, a.account_number, 
                   a.account_type, a.balance, a.status, a.created_date
            FROM bank_accounts a
            JOIN customers c ON a.customer_id = c.customer_id
            WHERE a.account_id = :1 AND a.customer_id = :2
        """, (account_id, customer_id))
        account = dictfetchone(cursor)

        if not account:
            return render_error(
                "Account Access Denied", 
                "The requested account was not found or does not belong to your authenticated profile.", 
                "/accounts", 
                "Back to Accounts"
            )

        # Transactions for this account
        cursor.execute("""
            SELECT transaction_id, transaction_type, amount,
                TO_CHAR(FROM_TZ(transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'DD-MM-YYYY') AS display_date,
                TO_CHAR(FROM_TZ(transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'HH12:MI AM') AS display_time,
                status
            FROM bank_transactions
            WHERE account_id = :1
            ORDER BY transaction_date DESC
        """, (account_id,))
        transactions = dictfetchall(cursor)

        # Totals
        cursor.execute("""
            SELECT 
                NVL(SUM(CASE WHEN transaction_type IN ('DEPOSIT', 'TRANSFER_IN') THEN amount ELSE 0 END), 0) AS total_deposits,
                NVL(SUM(CASE WHEN transaction_type IN ('WITHDRAWAL', 'TRANSFER_OUT') THEN amount ELSE 0 END), 0) AS total_withdrawals
            FROM bank_transactions
            WHERE account_id = :1 AND status = 'COMMITTED'
        """, (account_id,))
        totals = dictfetchone(cursor)
        total_deposits = Decimal(str(totals['total_deposits']))
        total_withdrawals = Decimal(str(totals['total_withdrawals']))

    except Exception as e:
        logger.error("Account detail error: %s", str(e), exc_info=True)
        return render_error("Error", "Failed to retrieve account details.", "/accounts", "Back to Accounts")
    finally:
        cursor.close()
        connection.close()

    return render_template(
        "customer/account_detail.html",
        account=account,
        transactions=transactions,
        total_deposits=total_deposits,
        total_withdrawals=total_withdrawals
    )


@app.route("/deposit", methods=["POST"])
@customer_required
def customer_deposit():
    if not validate_csrf():
        return render_error("Security Error", "Invalid CSRF token.", "/accounts", "Back to Accounts")

    customer_id = session.get("customer_id")
    if customer_id == DEMO_ACCOUNT_ID or str(session.get("email", "")).lower() == "demo@kapabank.com":
        return render_error(
            "Demo Mode Restricted",
            "The Demo Account is restricted exclusively to DBMS Transaction Control demonstrations (SAVEPOINT, COMMIT, ROLLBACK). Standard ad-hoc deposits are disabled on this account.",
            "/transaction-control",
            "Open Transaction Control"
        )

    account_id = request.form.get("account_id")
    amount_str = request.form.get("amount")

    amount, err = validate_positive_amount(amount_str)
    if err:
        return render_error("Invalid Deposit", err, "/accounts", "Back to Accounts")

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("SAVEPOINT before_deposit")

        # BACKEND OWNERSHIP CHECK + FOR UPDATE LOCK
        cursor.execute("""
            SELECT account_id, balance, status, account_number 
            FROM bank_accounts 
            WHERE account_id = :1 AND customer_id = :2 
            FOR UPDATE
        """, (account_id, customer_id))
        account = dictfetchone(cursor)

        if not account:
            connection.rollback()
            return render_error("Deposit Rejected", "Unauthorized account access or account does not exist.", "/accounts", "Back to Accounts")

        if account['status'] != 'ACTIVE':
            connection.rollback()
            return render_error("Account Inactive", f"Account {account['account_number']} is currently {account['status']}. Deposits are not permitted.", "/accounts", "Back to Accounts")

        old_balance = Decimal(str(account['balance']))
        new_balance = old_balance + amount

        cursor.execute("UPDATE bank_accounts SET balance = :1 WHERE account_id = :2", (new_balance, account_id))
        cursor.execute("""
            INSERT INTO bank_transactions (account_id, transaction_type, amount, status)
            VALUES (:1, 'DEPOSIT', :2, 'COMMITTED')
        """, (account_id, amount))

        log_audit("DEPOSIT", "ACCOUNT", account_id, f"Deposited INR {amount:,.2f} into account {account['account_number']}")

        connection.commit()
        return render_success(
            "Deposit Completed",
            f"INR {amount:,.2f} has been deposited into account {account['account_number']}.",
            amount=amount,
            old_balance=old_balance,
            new_balance=new_balance,
            back_url=url_for("customer_account_detail", account_id=account_id),
            back_label="View Account Details"
        )
    except Exception as e:
        connection.rollback()
        return render_error("Deposit Failed", safe_error_message(e), "/accounts", "Back to Accounts")
    finally:
        cursor.close()
        connection.close()


@app.route("/withdraw", methods=["POST"])
@customer_required
def customer_withdraw():
    if not validate_csrf():
        return render_error("Security Error", "Invalid CSRF token.", "/accounts", "Back to Accounts")

    customer_id = session.get("customer_id")
    if customer_id == DEMO_ACCOUNT_ID or str(session.get("email", "")).lower() == "demo@kapabank.com":
        return render_error(
            "Demo Mode Restricted",
            "The Demo Account is restricted exclusively to DBMS Transaction Control demonstrations (SAVEPOINT, COMMIT, ROLLBACK). Standard withdrawals are disabled on this account.",
            "/transaction-control",
            "Open Transaction Control"
        )

    account_id = request.form.get("account_id")
    amount_str = request.form.get("amount")

    amount, err = validate_positive_amount(amount_str)
    if err:
        return render_error("Invalid Withdrawal", err, "/accounts", "Back to Accounts")

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("SAVEPOINT before_withdraw")

        # BACKEND OWNERSHIP CHECK + FOR UPDATE LOCK
        cursor.execute("""
            SELECT account_id, balance, status, account_number 
            FROM bank_accounts 
            WHERE account_id = :1 AND customer_id = :2 
            FOR UPDATE
        """, (account_id, customer_id))
        account = dictfetchone(cursor)

        if not account:
            connection.rollback()
            return render_error("Withdrawal Rejected", "Unauthorized account access or account does not exist.", "/accounts", "Back to Accounts")

        if account['status'] != 'ACTIVE':
            connection.rollback()
            return render_error("Account Inactive", f"Account {account['account_number']} is {account['status']}. Withdrawals cannot be processed.", "/accounts", "Back to Accounts")

        old_balance = Decimal(str(account['balance']))
        if old_balance < amount:
            connection.rollback()
            return render_error("Insufficient Balance", f"Withdrawal of INR {amount:,.2f} failed. Current balance is INR {old_balance:,.2f}.", "/accounts", "Back to Accounts")

        new_balance = old_balance - amount

        cursor.execute("UPDATE bank_accounts SET balance = :1 WHERE account_id = :2", (new_balance, account_id))
        cursor.execute("""
            INSERT INTO bank_transactions (account_id, transaction_type, amount, status)
            VALUES (:1, 'WITHDRAWAL', :2, 'COMMITTED')
        """, (account_id, amount))

        log_audit("WITHDRAWAL", "ACCOUNT", account_id, f"Withdrew INR {amount:,.2f} from account {account['account_number']}")

        connection.commit()
        return render_success(
            "Withdrawal Completed",
            f"INR {amount:,.2f} was withdrawn from account {account['account_number']}.",
            amount=amount,
            old_balance=old_balance,
            new_balance=new_balance,
            back_url=url_for("customer_account_detail", account_id=account_id),
            back_label="View Account Details"
        )
    except Exception as e:
        connection.rollback()
        return render_error("Withdrawal Failed", safe_error_message(e), "/accounts", "Back to Accounts")
    finally:
        cursor.close()
        connection.close()


@app.route("/transfer", methods=["GET", "POST"])
@customer_required
def customer_transfer():
    customer_id = session.get("customer_id")
    if customer_id == DEMO_ACCOUNT_ID or str(session.get("email", "")).lower() == "demo@kapabank.com":
        return render_error(
            "Demo Mode Restricted",
            "The Demo Account is restricted exclusively to DBMS Transaction Control demonstrations (SAVEPOINT, COMMIT, ROLLBACK). General fund transfers are not permitted on this demonstration account.",
            "/transaction-control",
            "Open Transaction Control"
        )

    connection = get_connection()
    cursor = connection.cursor()

    if request.method == "GET":
        try:
            # Own accounts for source dropdown
            cursor.execute("""
                SELECT account_id, account_number, account_type, balance, status
                FROM bank_accounts
                WHERE customer_id = :1 AND status = 'ACTIVE'
                ORDER BY account_number ASC
            """, (customer_id,))
            my_accounts = dictfetchall(cursor)

            # Destination accounts across system (excluding own)
            cursor.execute("""
                SELECT a.account_id, a.account_number, c.name AS customer_name
                FROM bank_accounts a
                JOIN customers c ON a.customer_id = c.customer_id
                WHERE a.status = 'ACTIVE'
                ORDER BY a.account_number ASC
            """)
            all_accounts = dictfetchall(cursor)

            return render_template("customer/transfer.html", my_accounts=my_accounts, all_accounts=all_accounts)
        finally:
            cursor.close()
            connection.close()

    # POST Transfer
    if not validate_csrf():
        return render_error("Security Error", "Invalid CSRF token.", "/transfer", "Back to Transfer")

    try:
        from_account_id = int(request.form.get("from_account", "0"))
        to_account_id = int(request.form.get("to_account", "0"))
        amount_str = request.form.get("amount")

        amount, err = validate_positive_amount(amount_str)
        if err:
            return render_error("Invalid Transfer Amount", err, "/transfer", "Back to Transfer")

        if from_account_id == to_account_id:
            return render_error("Transfer Rejected", "Origin and destination bank accounts must be different.", "/transfer", "Back to Transfer")

        cursor.execute("SAVEPOINT before_transfer")

        # DEADLOCK PREVENTION: Lock accounts in strictly ascending numeric order
        first_acc_id = min(from_account_id, to_account_id)
        second_acc_id = max(from_account_id, to_account_id)

        cursor.execute("SELECT account_id, customer_id, account_number, balance, status FROM bank_accounts WHERE account_id = :1 FOR UPDATE", (first_acc_id,))
        first_acc = dictfetchone(cursor)

        cursor.execute("SELECT account_id, customer_id, account_number, balance, status FROM bank_accounts WHERE account_id = :1 FOR UPDATE", (second_acc_id,))
        second_acc = dictfetchone(cursor)

        if not first_acc or not second_acc:
            connection.rollback()
            return render_error("Transfer Failed", "One or both selected bank accounts do not exist.", "/transfer", "Back to Transfer")

        sender = first_acc if first_acc['account_id'] == from_account_id else second_acc
        receiver = second_acc if second_acc['account_id'] == to_account_id else first_acc

        # STRICT BACKEND ISOLATION: Verify sender account belongs to current customer
        if sender['customer_id'] != customer_id:
            connection.rollback()
            log_audit("UNAUTHORIZED_TRANSFER_ATTEMPT", "ACCOUNT", from_account_id, f"Customer {customer_id} tried to transfer from account {sender['account_number']}")
            return render_error("Security Violation", "You are only permitted to initiate transfers from your own accounts.", "/transfer", "Back to Transfer")

        if sender['status'] != 'ACTIVE' or receiver['status'] != 'ACTIVE':
            connection.rollback()
            return render_error("Transfer Blocked", "Both sender and recipient accounts must be ACTIVE.", "/transfer", "Back to Transfer")

        sender_balance = Decimal(str(sender['balance']))
        if sender_balance < amount:
            connection.rollback()
            return render_error("Insufficient Balance", f"Transfer of INR {amount:,.2f} exceeds available balance of INR {sender_balance:,.2f}.", "/transfer", "Back to Transfer")

        # Atomically update both account balances
        cursor.execute("UPDATE bank_accounts SET balance = balance - :1 WHERE account_id = :2", (amount, from_account_id))
        cursor.execute("UPDATE bank_accounts SET balance = balance + :1 WHERE account_id = :2", (amount, to_account_id))

        # Insert transfer record
        cursor.execute("""
            INSERT INTO bank_transfers (from_account, to_account, amount, status)
            VALUES (:1, :2, :3, 'COMMITTED')
        """, (from_account_id, to_account_id, amount))

        # Insert double-entry ledger transactions
        cursor.execute("""
            INSERT INTO bank_transactions (account_id, transaction_type, amount, status)
            VALUES (:1, 'TRANSFER_OUT', :2, 'COMMITTED')
        """, (from_account_id, amount))

        cursor.execute("""
            INSERT INTO bank_transactions (account_id, transaction_type, amount, status)
            VALUES (:1, 'TRANSFER_IN', :2, 'COMMITTED')
        """, (to_account_id, amount))

        log_audit("TRANSFER_COMPLETED", "TRANSFER", from_account_id, f"Transferred INR {amount:,.2f} from {sender['account_number']} to {receiver['account_number']}")

        connection.commit()
        return render_success(
            "Transfer Completed Successfully",
            f"INR {amount:,.2f} transferred from {sender['account_number']} to {receiver['account_number']}.",
            amount=amount,
            from_account=sender['account_number'],
            to_account=receiver['account_number'],
            back_url=url_for("customer_transactions"),
            back_label="View Transaction History"
        )

    except Exception as e:
        connection.rollback()
        return render_error("Transfer Execution Error", safe_error_message(e), "/transfer", "Back to Transfer")
    finally:
        cursor.close()
        connection.close()


@app.route("/transactions")
@customer_required
def customer_transactions():
    customer_id = session.get("customer_id")
    search_query = request.args.get('q', '').strip()
    filter_type = request.args.get('type', '').strip()
    filter_status = request.args.get('status', '').strip()
    filter_acc = request.args.get('account_id', '').strip()

    connection = get_connection()
    cursor = connection.cursor()

    try:
        # Customer's accounts for dropdown
        cursor.execute("SELECT account_id, account_number FROM bank_accounts WHERE customer_id = :1 ORDER BY account_number ASC", (customer_id,))
        customer_accounts = dictfetchall(cursor)

        sql = """
            SELECT t.transaction_id, t.account_id, a.account_number, t.transaction_type, t.amount,
                TO_CHAR(FROM_TZ(t.transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'DD-MM-YYYY') AS display_date,
                TO_CHAR(FROM_TZ(t.transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'HH12:MI AM') AS display_time,
                t.status
            FROM bank_transactions t
            JOIN bank_accounts a ON t.account_id = a.account_id
            WHERE a.customer_id = :cid
        """
        params = {"cid": customer_id}

        if search_query:
            sql += " AND LOWER(a.account_number) LIKE LOWER(:q)"
            params['q'] = f"%{search_query}%"
        if filter_type:
            sql += " AND t.transaction_type = :ft"
            params['ft'] = filter_type
        if filter_status:
            sql += " AND t.status = :fs"
            params['fs'] = filter_status
        if filter_acc and filter_acc.isdigit():
            sql += " AND a.account_id = :fa"
            params['fa'] = int(filter_acc)

        sql += " ORDER BY t.transaction_date DESC"
        cursor.execute(sql, params)
        transactions_list = dictfetchall(cursor)

    except Exception as e:
        logger.error("Transactions listing error: %s", str(e), exc_info=True)
        transactions_list = []
        customer_accounts = []
    finally:
        cursor.close()
        connection.close()

    return render_template(
        "customer/transactions.html",
        transactions=transactions_list,
        accounts=customer_accounts,
        search_query=search_query,
        filter_type=filter_type,
        filter_status=filter_status,
        filter_acc=filter_acc
    )


@app.route("/statements")
@customer_required
def customer_statements():
    if session.get("is_demo") or session.get("customer_id") == DEMO_ACCOUNT_ID:
        return redirect("/transaction-control")

    customer_id = session.get("customer_id")
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            SELECT account_id, account_number, account_type, balance, status
            FROM bank_accounts
            WHERE customer_id = :1
            ORDER BY account_number ASC
        """, (customer_id,))
        accounts = dictfetchall(cursor)
    finally:
        cursor.close()
        connection.close()

    return render_template("customer/statements.html", accounts=accounts)


@app.route("/statements/download/pdf/<int:account_id>")
@customer_required
def customer_download_pdf_statement(account_id):
    customer_id = session.get("customer_id")
    connection = get_connection()
    cursor = connection.cursor()

    try:
        # STRICT OWNERSHIP CHECK
        cursor.execute("""
            SELECT account_id, customer_id, account_number, account_type, balance, status
            FROM bank_accounts
            WHERE account_id = :1 AND customer_id = :2
        """, (account_id, customer_id))
        account = dictfetchone(cursor)

        if not account:
            return render_error("Unauthorized", "You cannot download statements for accounts you do not own.", "/statements", "Back to Statements")

        cursor.execute("SELECT customer_id, name, email, phone, address FROM customers WHERE customer_id = :1", (customer_id,))
        customer = dictfetchone(cursor)

        cursor.execute("""
            SELECT transaction_id, transaction_type, amount,
                TO_CHAR(FROM_TZ(transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'DD-MM-YYYY') AS display_date,
                TO_CHAR(FROM_TZ(transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'HH12:MI AM') AS display_time,
                status
            FROM bank_transactions
            WHERE account_id = :1
            ORDER BY transaction_date DESC
        """, (account_id,))
        transactions = dictfetchall(cursor)

        pdf_bytes = generate_pdf_statement(customer, account, transactions)

        log_audit("STATEMENT_DOWNLOAD_PDF", "ACCOUNT", account_id, f"Downloaded PDF statement for account {account['account_number']}")

        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=KAPA_Statement_{account["account_number"]}.pdf'
        return response

    except Exception as e:
        logger.error("PDF generation failed: %s", str(e), exc_info=True)
        return render_error("Generation Error", "Failed to compile your PDF bank statement.", "/statements", "Back to Statements")
    finally:
        cursor.close()
        connection.close()


@app.route("/statements/download/csv/<int:account_id>")
@customer_required
def customer_download_csv_statement(account_id):
    customer_id = session.get("customer_id")
    connection = get_connection()
    cursor = connection.cursor()

    try:
        # STRICT OWNERSHIP CHECK
        cursor.execute("""
            SELECT account_id, customer_id, account_number, account_type, balance, status
            FROM bank_accounts
            WHERE account_id = :1 AND customer_id = :2
        """, (account_id, customer_id))
        account = dictfetchone(cursor)

        if not account:
            return render_error("Unauthorized", "You cannot export statements for accounts you do not own.", "/statements", "Back to Statements")

        cursor.execute("SELECT customer_id, name, email, phone, address FROM customers WHERE customer_id = :1", (customer_id,))
        customer = dictfetchone(cursor)

        cursor.execute("""
            SELECT transaction_id, transaction_type, amount,
                TO_CHAR(FROM_TZ(transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'DD-MM-YYYY') AS display_date,
                TO_CHAR(FROM_TZ(transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'HH12:MI AM') AS display_time,
                status
            FROM bank_transactions
            WHERE account_id = :1
            ORDER BY transaction_date DESC
        """, (account_id,))
        transactions = dictfetchall(cursor)

        csv_content = generate_csv_statement(customer, account, transactions)

        log_audit("STATEMENT_EXPORT_CSV", "ACCOUNT", account_id, f"Exported CSV statement for account {account['account_number']}")

        response = make_response(csv_content)
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=KAPA_Transactions_{account["account_number"]}.csv'
        return response

    except Exception as e:
        logger.error("CSV export failed: %s", str(e), exc_info=True)
        return render_error("Export Error", "Failed to export your CSV statement.", "/statements", "Back to Statements")
    finally:
        cursor.close()
        connection.close()


@app.route("/profile")
@customer_required
def customer_profile():
    customer_id = session.get("customer_id")
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            SELECT c.customer_id, c.name, c.email, c.phone, c.address, u.user_id, u.created_at, u.last_login
            FROM customers c
            JOIN users u ON c.customer_id = u.customer_id
            WHERE c.customer_id = :1
        """, (customer_id,))
        profile = dictfetchone(cursor)

        cursor.execute("SELECT COUNT(*) AS count, NVL(SUM(balance), 0) AS total FROM bank_accounts WHERE customer_id = :1", (customer_id,))
        acc_stats = dictfetchone(cursor)

    except Exception as e:
        logger.error("Profile load error: %s", str(e), exc_info=True)
        return render_error("Error", "Failed to load customer profile.", "/", "Dashboard")
    finally:
        cursor.close()
        connection.close()

    return render_template("customer/profile.html", profile=profile, acc_stats=acc_stats)


@app.route("/profile/change-password", methods=["POST"])
@customer_required
def customer_change_password():
    if not validate_csrf():
        return render_error("Security Error", "Invalid CSRF token.", "/profile", "Back to Profile")

    user_id = session.get("user_id")
    current_password = request.form.get("current_password", "").strip()
    new_password = request.form.get("new_password", "").strip()
    confirm_password = request.form.get("confirm_password", "").strip()

    if not current_password or not new_password:
        return render_error("Validation Error", "All password fields are required.", "/profile", "Back to Profile")

    if len(new_password) < 6:
        return render_error("Weak Password", "New password must be at least 6 characters.", "/profile", "Back to Profile")

    if new_password != confirm_password:
        return render_error("Mismatch", "New password and confirmation password do not match.", "/profile", "Back to Profile")

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("SELECT password_hash FROM users WHERE user_id = :1", (user_id,))
        user = dictfetchone(cursor)

        if not user or not check_password_hash(user['password_hash'], current_password):
            return render_error("Incorrect Password", "Current password entered is incorrect.", "/profile", "Back to Profile")

        new_hash = generate_password_hash(new_password)
        cursor.execute("UPDATE users SET password_hash = :1, display_password = :2 WHERE user_id = :3", (new_hash, new_password, user_id))
        connection.commit()

        log_audit("PASSWORD_CHANGED", "USER", user_id, "User updated their login password")

        return render_success("Password Updated", "Your password has been changed successfully.", back_url="/profile", back_label="Return to Profile")

    except Exception as e:
        connection.rollback()
        return render_error("Update Failed", safe_error_message(e), "/profile", "Back to Profile")
    finally:
        cursor.close()
        connection.close()


# ============================================================
# ADMINISTRATIVE PORTAL ROUTES (ADMIN ONLY)
# ============================================================

@app.route("/admin")
@admin_required
def admin_dashboard():
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("SELECT COUNT(*) AS count FROM customers")
        customer_count = dictfetchone(cursor)['count']

        cursor.execute("SELECT COUNT(*) AS count FROM bank_accounts")
        account_count = dictfetchone(cursor)['count']

        cursor.execute("SELECT NVL(SUM(balance), 0) AS total FROM bank_accounts WHERE status = 'ACTIVE'")
        total_balance = Decimal(str(dictfetchone(cursor)['total']))

        cursor.execute("SELECT COUNT(*) AS count FROM bank_transactions")
        transaction_count = dictfetchone(cursor)['count']

        cursor.execute("""
            SELECT 
                t.transaction_id, 
                t.account_id, 
                a.account_number, 
                c.name AS customer_name,
                t.transaction_type, 
                t.amount, 
                TO_CHAR(FROM_TZ(t.transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'DD-MM-YYYY') AS display_date,
                TO_CHAR(FROM_TZ(t.transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'HH12:MI AM') AS display_time,
                t.status
            FROM bank_transactions t
            JOIN bank_accounts a ON t.account_id = a.account_id
            JOIN customers c ON a.customer_id = c.customer_id
            ORDER BY t.transaction_date DESC
            FETCH FIRST 6 ROWS ONLY
        """)
        recent_transactions = dictfetchall(cursor)

        cursor.execute("""
            SELECT account_type, COUNT(*) AS count, NVL(SUM(balance), 0) AS total_balance
            FROM bank_accounts
            GROUP BY account_type
        """)
        account_type_data = dictfetchall(cursor)

        cursor.execute("""
            SELECT status, COUNT(*) AS count
            FROM bank_accounts
            GROUP BY status
        """)
        status_data = dictfetchall(cursor)

    except Exception as e:
        logger.error("Admin dashboard error: %s", str(e), exc_info=True)
        return render_error("Admin Portal Error", "Failed to retrieve management statistics.", "/logout", "Log Out")
    finally:
        cursor.close()
        connection.close()

    return render_template(
        "admin/dashboard.html",
        customer_count=customer_count,
        account_count=account_count,
        total_balance=total_balance,
        transaction_count=transaction_count,
        recent_transactions=recent_transactions,
        account_types=account_type_data,
        status_counts=status_data
    )


@app.route("/admin/customers")
@admin_required
def admin_customers():
    search_query = request.args.get('q', '').strip()
    connection = get_connection()
    cursor = connection.cursor()

    try:
        sql = """
            SELECT c.customer_id, c.name, c.email, c.phone, c.address, 
                   COUNT(a.account_id) AS account_count,
                   NVL(SUM(a.balance), 0) AS total_balance
            FROM customers c
            LEFT JOIN bank_accounts a ON c.customer_id = a.customer_id
        """
        params = {}
        if search_query:
            sql += " WHERE LOWER(c.name) LIKE LOWER(:q) OR LOWER(c.email) LIKE LOWER(:q) OR c.phone LIKE :q"
            params['q'] = f"%{search_query}%"

        sql += " GROUP BY c.customer_id, c.name, c.email, c.phone, c.address ORDER BY c.name ASC"
        cursor.execute(sql, params)
        customers_list = dictfetchall(cursor)
    except Exception as e:
        logger.error("Admin customers error: %s", str(e), exc_info=True)
        customers_list = []
    finally:
        cursor.close()
        connection.close()

    return render_template("admin/customers.html", customers=customers_list, search_query=search_query)


@app.route("/admin/add-customer", methods=["POST"])
@admin_required
def admin_add_customer():
    if not validate_csrf():
        return render_error("Security Error", "Invalid CSRF token.", "/admin/customers", "Back to Customers")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    address = request.form.get("address", "").strip()
    initial_password = request.form.get("initial_password", "Customer@123").strip()

    if err := validate_required(name, "Name"):
        return render_error("Validation Error", err, "/admin/customers", "Back")
    if err := validate_required(email, "Email"):
        return render_error("Validation Error", err, "/admin/customers", "Back")
    if err := validate_required(phone, "Phone"):
        return render_error("Validation Error", err, "/admin/customers", "Back")

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("SAVEPOINT before_admin_add_cust")

        cursor.execute("""
            INSERT INTO customers (name, email, phone, address)
            VALUES (:1, :2, :3, :4)
        """, (name, email, phone, address))

        cursor.execute("SELECT customer_id FROM customers WHERE LOWER(email) = :1", (email,))
        cid = dictfetchone(cursor)['customer_id']

        pwd_hash = generate_password_hash(initial_password)
        cursor.execute("""
            INSERT INTO users (email, password_hash, role, customer_id, is_active, display_password)
            VALUES (:1, :2, 'CUSTOMER', :3, 1, :4)
        """, (email, pwd_hash, cid, initial_password))

        log_audit("ADMIN_CREATE_CUSTOMER", "CUSTOMER", cid, f"Admin provisioned customer {name} ({email})")

        connection.commit()
        return render_success(
            "Customer Registered",
            f"Customer {name} was successfully registered with temporary password '{initial_password}'.",
            back_url="/admin/customers",
            back_label="View All Customers"
        )
    except Exception as e:
        connection.rollback()
        return render_error("Customer Creation Failed", safe_error_message(e), "/admin/customers", "Back")
    finally:
        cursor.close()
        connection.close()


@app.route("/admin/customers/<int:customer_id>")
@admin_required
def admin_customer_detail(customer_id):
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("SELECT customer_id, name, email, phone, address FROM customers WHERE customer_id = :1", (customer_id,))
        customer = dictfetchone(cursor)
        if not customer:
            return render_error("Not Found", "Customer does not exist.", "/admin/customers", "Back to Customers")

        cursor.execute("""
            SELECT account_id, account_number, account_type, balance, status, created_date
            FROM bank_accounts
            WHERE customer_id = :1
            ORDER BY created_date DESC
        """, (customer_id,))
        accounts = dictfetchall(cursor)

        cursor.execute("""
            SELECT COUNT(t.transaction_id) AS tx_count
            FROM bank_transactions t
            JOIN bank_accounts a ON t.account_id = a.account_id
            WHERE a.customer_id = :1
        """, (customer_id,))
        tx_count = dictfetchone(cursor)['tx_count']

        cursor.execute("SELECT user_id, is_active, last_login, created_at FROM users WHERE customer_id = :1", (customer_id,))
        user_info = dictfetchone(cursor)

    except Exception as e:
        logger.error("Admin customer detail error: %s", str(e), exc_info=True)
        return render_error("Error", "Failed to retrieve customer record.", "/admin/customers", "Back")
    finally:
        cursor.close()
        connection.close()

    return render_template(
        "admin/customer_detail.html",
        customer=customer,
        accounts=accounts,
        tx_count=tx_count,
        user_info=user_info
    )


@app.route("/admin/accounts")
@admin_required
def admin_accounts():
    search_query = request.args.get('q', '').strip()
    filter_type = request.args.get('type', '').strip()
    filter_status = request.args.get('status', '').strip()

    connection = get_connection()
    cursor = connection.cursor()

    try:
        sql = """
            SELECT a.account_id, a.customer_id, c.name AS customer_name, c.email AS customer_email,
                   a.account_number, a.account_type, a.balance, a.status, a.created_date
            FROM bank_accounts a
            JOIN customers c ON a.customer_id = c.customer_id
            WHERE 1=1
        """
        params = {}
        if search_query:
            sql += " AND (LOWER(a.account_number) LIKE LOWER(:q) OR LOWER(c.name) LIKE LOWER(:q))"
            params['q'] = f"%{search_query}%"
        if filter_type:
            sql += " AND a.account_type = :ft"
            params['ft'] = filter_type
        if filter_status:
            sql += " AND a.status = :fs"
            params['fs'] = filter_status

        sql += " ORDER BY a.created_date DESC"
        cursor.execute(sql, params)
        accounts_list = dictfetchall(cursor)

        cursor.execute("SELECT customer_id, name, email FROM customers ORDER BY name ASC")
        customers_list = dictfetchall(cursor)

    except Exception as e:
        logger.error("Admin accounts error: %s", str(e), exc_info=True)
        accounts_list = []
        customers_list = []
    finally:
        cursor.close()
        connection.close()

    return render_template(
        "admin/accounts.html",
        accounts=accounts_list,
        customers=customers_list,
        search_query=search_query,
        filter_type=filter_type,
        filter_status=filter_status
    )


@app.route("/admin/add-account", methods=["POST"])
@admin_required
def admin_add_account():
    if not validate_csrf():
        return render_error("Security Error", "Invalid CSRF token.", "/admin/accounts", "Back to Accounts")

    customer_id_str = request.form.get("customer_id", "").strip()
    account_number = request.form.get("account_number", "").strip()
    account_type = request.form.get("account_type", "").strip()

    if not customer_id_str.isdigit():
        return render_error("Validation Error", "Please select a valid customer.", "/admin/accounts", "Back")
    customer_id = int(customer_id_str)

    if not account_number:
        account_number = f"ACC{secrets.randbelow(9000000) + 1000000}"

    if account_type not in ["SAVINGS", "CURRENT"]:
        return render_error("Validation Error", "Invalid account type selected.", "/admin/accounts", "Back")

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            INSERT INTO bank_accounts (customer_id, account_number, account_type, balance, status)
            VALUES (:1, :2, :3, 0, 'ACTIVE')
        """, (customer_id, account_number, account_type))

        cursor.execute("SELECT account_id FROM bank_accounts WHERE account_number = :1", (account_number,))
        aid = dictfetchone(cursor)['account_id']

        log_audit("ADMIN_CREATE_ACCOUNT", "ACCOUNT", aid, f"Admin opened {account_type} account {account_number} for customer {customer_id}")

        connection.commit()
        return render_success(
            "Account Provisioned",
            f"Bank account {account_number} ({account_type}) opened successfully.",
            back_url="/admin/accounts",
            back_label="Back to Accounts"
        )
    except Exception as e:
        connection.rollback()
        return render_error("Account Creation Failed", safe_error_message(e), "/admin/accounts", "Back")
    finally:
        cursor.close()
        connection.close()


@app.route("/admin/accounts/<int:account_id>")
@admin_required
def admin_account_detail(account_id):
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            SELECT a.account_id, a.customer_id, c.name AS customer_name, c.email AS customer_email,
                   a.account_number, a.account_type, a.balance, a.status, a.created_date
            FROM bank_accounts a
            JOIN customers c ON a.customer_id = c.customer_id
            WHERE a.account_id = :1
        """, (account_id,))
        account = dictfetchone(cursor)

        if not account:
            return render_error("Not Found", "Account not found.", "/admin/accounts", "Back to Accounts")

        cursor.execute("""
            SELECT transaction_id, transaction_type, amount,
                TO_CHAR(FROM_TZ(transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'DD-MM-YYYY') AS display_date,
                TO_CHAR(FROM_TZ(transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'HH12:MI AM') AS display_time,
                status
            FROM bank_transactions
            WHERE account_id = :1
            ORDER BY transaction_date DESC
        """, (account_id,))
        transactions = dictfetchall(cursor)

        cursor.execute("""
            SELECT 
                NVL(SUM(CASE WHEN transaction_type IN ('DEPOSIT', 'TRANSFER_IN') THEN amount ELSE 0 END), 0) AS total_deposits,
                NVL(SUM(CASE WHEN transaction_type IN ('WITHDRAWAL', 'TRANSFER_OUT') THEN amount ELSE 0 END), 0) AS total_withdrawals
            FROM bank_transactions
            WHERE account_id = :1 AND status = 'COMMITTED'
        """, (account_id,))
        totals = dictfetchone(cursor)
        total_deposits = Decimal(str(totals['total_deposits']))
        total_withdrawals = Decimal(str(totals['total_withdrawals']))

    except Exception as e:
        logger.error("Admin account detail error: %s", str(e), exc_info=True)
        return render_error("Error", "Failed to retrieve account details.", "/admin/accounts", "Back")
    finally:
        cursor.close()
        connection.close()

    return render_template(
        "admin/account_detail.html",
        account=account,
        transactions=transactions,
        total_deposits=total_deposits,
        total_withdrawals=total_withdrawals
    )


@app.route("/admin/accounts/<int:account_id>/status", methods=["POST"])
@admin_required
def admin_set_account_status(account_id):
    if not validate_csrf():
        return render_error("Security Error", "Invalid CSRF token.", "/admin/accounts", "Back")

    new_status = request.form.get("status", "").strip()
    if new_status not in ["ACTIVE", "BLOCKED", "CLOSED"]:
        return render_error("Validation Error", "Invalid account status value.", f"/admin/accounts/{account_id}", "Back")

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("SELECT account_number, status FROM bank_accounts WHERE account_id = :1", (account_id,))
        acc = dictfetchone(cursor)
        if not acc:
            return render_error("Not Found", "Account does not exist.", "/admin/accounts", "Back")

        cursor.execute("UPDATE bank_accounts SET status = :1 WHERE account_id = :2", (new_status, account_id))
        log_audit("ACCOUNT_STATUS_CHANGE", "ACCOUNT", account_id, f"Changed status of {acc['account_number']} from {acc['status']} to {new_status}")

        connection.commit()
        return render_success(
            "Status Updated",
            f"Account {acc['account_number']} status updated to {new_status}.",
            back_url=f"/admin/accounts/{account_id}",
            back_label="Back to Account"
        )
    except Exception as e:
        connection.rollback()
        return render_error("Status Change Failed", safe_error_message(e), f"/admin/accounts/{account_id}", "Back")
    finally:
        cursor.close()
        connection.close()


@app.route("/admin/transactions")
@admin_required
def admin_transactions():
    search_query = request.args.get('q', '').strip()
    filter_type = request.args.get('type', '').strip()
    filter_status = request.args.get('status', '').strip()

    connection = get_connection()
    cursor = connection.cursor()

    try:
        sql = """
            SELECT t.transaction_id, t.account_id, a.account_number, c.name AS customer_name,
                   t.transaction_type, t.amount,
                   TO_CHAR(FROM_TZ(t.transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'DD-MM-YYYY') AS display_date,
                   TO_CHAR(FROM_TZ(t.transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'HH12:MI AM') AS display_time,
                   t.status
            FROM bank_transactions t
            JOIN bank_accounts a ON t.account_id = a.account_id
            JOIN customers c ON a.customer_id = c.customer_id
            WHERE 1=1
        """
        params = {}
        if search_query:
            sql += " AND (LOWER(a.account_number) LIKE LOWER(:q) OR LOWER(c.name) LIKE LOWER(:q))"
            params['q'] = f"%{search_query}%"
        if filter_type:
            sql += " AND t.transaction_type = :ft"
            params['ft'] = filter_type
        if filter_status:
            sql += " AND t.status = :fs"
            params['fs'] = filter_status

        sql += " ORDER BY t.transaction_date DESC"
        cursor.execute(sql, params)
        transactions_list = dictfetchall(cursor)

    except Exception as e:
        logger.error("Admin transactions list error: %s", str(e), exc_info=True)
        transactions_list = []
    finally:
        cursor.close()
        connection.close()

    return render_template(
        "admin/transactions.html",
        transactions=transactions_list,
        search_query=search_query,
        filter_type=filter_type,
        filter_status=filter_status
    )


@app.route("/admin/reports")
@admin_required
def admin_reports():
    connection = get_connection()
    cursor = connection.cursor()

    try:
        # 1. Total Volume Aggregates
        cursor.execute("""
            SELECT 
                NVL(SUM(CASE WHEN transaction_type = 'DEPOSIT' THEN amount ELSE 0 END), 0) AS total_deposits,
                NVL(SUM(CASE WHEN transaction_type = 'WITHDRAWAL' THEN amount ELSE 0 END), 0) AS total_withdrawals,
                NVL(SUM(CASE WHEN transaction_type = 'TRANSFER_OUT' THEN amount ELSE 0 END), 0) AS total_transfers
            FROM bank_transactions WHERE status = 'COMMITTED'
        """)
        totals = dictfetchone(cursor)
        total_deposits = Decimal(str(totals['total_deposits']))
        total_withdrawals = Decimal(str(totals['total_withdrawals']))
        total_transfers = Decimal(str(totals['total_transfers']))

        # 2. Breakdown by Type
        cursor.execute("""
            SELECT transaction_type, COUNT(*) AS count, NVL(SUM(amount), 0) AS total
            FROM bank_transactions
            WHERE status = 'COMMITTED'
            GROUP BY transaction_type
        """)
        transaction_type_counts = dictfetchall(cursor)

        # 3. Account Type Distribution
        cursor.execute("""
            SELECT account_type, COUNT(*) AS count, NVL(SUM(balance), 0) AS total_balance
            FROM bank_accounts
            GROUP BY account_type
        """)
        account_type_counts = dictfetchall(cursor)

        # 4. Top 5 Balances
        cursor.execute("""
            SELECT a.account_number, c.name AS customer_name, a.balance
            FROM bank_accounts a
            JOIN customers c ON a.customer_id = c.customer_id
            ORDER BY a.balance DESC
            FETCH FIRST 5 ROWS ONLY
        """)
        top_accounts = dictfetchall(cursor)

        # 5. Counts
        cursor.execute("SELECT COUNT(*) AS count FROM customers")
        customer_count = dictfetchone(cursor)['count']

        cursor.execute("SELECT COUNT(*) AS count FROM bank_accounts")
        account_count = dictfetchone(cursor)['count']

        cursor.execute("SELECT NVL(SUM(balance), 0) AS total FROM bank_accounts WHERE status = 'ACTIVE'")
        total_balance = Decimal(str(dictfetchone(cursor)['total']))

    except Exception as e:
        logger.error("Admin reports error: %s", str(e), exc_info=True)
        return render_error("Reporting Error", "Failed to compile aggregate database metrics.", "/admin", "Back to Admin")
    finally:
        cursor.close()
        connection.close()

    return render_template(
        "admin/reports.html",
        total_deposits=total_deposits,
        total_withdrawals=total_withdrawals,
        total_transfers=total_transfers,
        transaction_type_counts=transaction_type_counts,
        account_type_counts=account_type_counts,
        top_accounts=top_accounts,
        customer_count=customer_count,
        account_count=account_count,
        total_balance=total_balance
    )


@app.route("/admin/audit-log")
@admin_required
def admin_audit_log():
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            SELECT 
                l.audit_id, 
                l.user_id, 
                u.email AS user_email, 
                l.action, 
                l.entity_type, 
                l.entity_id, 
                l.details, 
                l.ip_address,
                TO_CHAR(FROM_TZ(l.created_at, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'DD-MM-YYYY HH12:MI:SS AM') AS timestamp_str
            FROM audit_log l
            LEFT JOIN users u ON l.user_id = u.user_id
            ORDER BY l.created_at DESC
            FETCH FIRST 100 ROWS ONLY
        """)
        logs = dictfetchall(cursor)
    except Exception as e:
        logger.error("Audit log read error: %s", str(e), exc_info=True)
        logs = []
    finally:
        cursor.close()
        connection.close()

    return render_template("admin/audit_log.html", logs=logs)


# ============================================================
# DBMS TRANSACTION CONTROL DEMONSTRATIONS (TCL & ACID)
# ============================================================

@app.route("/transaction-control")
@app.route("/admin/transaction-control")
@login_required
def transaction_control_page():
    role = session.get("role")
    cid = session.get("customer_id")
    is_demo = (cid == DEMO_ACCOUNT_ID or str(session.get("email", "")).lower() == "demo@kapabank.com")
    
    if role != "ADMIN" and not is_demo:
        return render_error("Access Restricted", 
                            "The Transaction Control demonstration is accessible only to the Administrator and the dedicated Demo Customer account.", 
                            "/", "Return to Dashboard")

    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT account_id, account_number, balance FROM bank_accounts WHERE account_id = :1", (DEMO_ACCOUNT_ID,))
        account = dictfetchone(cursor)
        if not account:
            return render_error("Demo Account Not Found", f"Demonstration account ID {DEMO_ACCOUNT_ID} is missing.", "/", "Home")

        cursor.execute("""
            SELECT transaction_id, transaction_type, amount, status,
                   TO_CHAR(FROM_TZ(transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'DD-MM-YYYY') AS display_date,
                   TO_CHAR(FROM_TZ(transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'HH12:MI AM') AS display_time
            FROM bank_transactions
            WHERE account_id = :1
            ORDER BY transaction_date DESC
            FETCH FIRST 10 ROWS ONLY
        """, (DEMO_ACCOUNT_ID,))
        demo_txs = dictfetchall(cursor)
    except Exception as e:
        logger.error("Demo load error: %s", str(e), exc_info=True)
        return render_error("Error", "Failed to load demo account.", "/", "Home")
    finally:
        cursor.close()
        connection.close()

    is_admin = (role == "ADMIN")
    return render_template("admin/transaction_control.html", account=account, demo_txs=demo_txs, is_admin=is_admin)


@app.route("/transaction-control/commit", methods=["POST"])
@app.route("/admin/transaction-control/commit", methods=["POST"])
@login_required
def demo_commit():
    role = session.get("role")
    cid = session.get("customer_id")
    is_demo = (cid == DEMO_ACCOUNT_ID or str(session.get("email", "")).lower() == "demo@kapabank.com")
    back_url = "/admin/transaction-control" if role == "ADMIN" else "/transaction-control"

    if not validate_csrf():
        return render_error("Security Error", "Invalid CSRF token.", back_url, "Back")

    if role != "ADMIN" and not is_demo:
        return render_error("Access Forbidden", "Only Administrator and the Demo Customer can execute TCL operations.", back_url, "Back")

    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT balance FROM bank_accounts WHERE account_id = :1 FOR UPDATE", (DEMO_ACCOUNT_ID,))
        account = dictfetchone(cursor)
        old_balance = Decimal(str(account['balance']))

        cursor.execute("SAVEPOINT before_demo")
        new_balance = old_balance + Decimal('1000')

        cursor.execute("UPDATE bank_accounts SET balance = :1 WHERE account_id = :2", (new_balance, DEMO_ACCOUNT_ID))
        cursor.execute("INSERT INTO bank_transactions (account_id, transaction_type, amount, status) VALUES (:1, 'DEPOSIT', 1000, 'COMMITTED')", (DEMO_ACCOUNT_ID,))

        connection.commit()
        log_audit("DEMO_COMMIT", "ACCOUNT", DEMO_ACCOUNT_ID, "Executed COMMIT demonstration (+1000)")

        return render_success(
            "Transaction Committed Permanently",
            "The balance was incremented by INR 1,000.00 and permanently written to Oracle database disk via COMMIT.",
            old_balance=old_balance,
            new_balance=new_balance,
            transaction_status='COMMITTED',
            back_url=back_url,
            back_label="Back to Transaction Control",
            transaction_demo=True
        )
    except Exception as e:
        connection.rollback()
        return render_error("Commit Demo Failed", safe_error_message(e), back_url, "Back")
    finally:
        cursor.close()
        connection.close()


@app.route("/transaction-control/rollback", methods=["POST"])
@app.route("/admin/transaction-control/rollback", methods=["POST"])
@login_required
def demo_rollback():
    role = session.get("role")
    cid = session.get("customer_id")
    is_demo = (cid == DEMO_ACCOUNT_ID or str(session.get("email", "")).lower() == "demo@kapabank.com")
    back_url = "/admin/transaction-control" if role == "ADMIN" else "/transaction-control"

    if not validate_csrf():
        return render_error("Security Error", "Invalid CSRF token.", back_url, "Back")

    if role != "ADMIN" and not is_demo:
        return render_error("Access Forbidden", "Only Administrator and the Demo Customer can execute TCL operations.", back_url, "Back")

    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT balance FROM bank_accounts WHERE account_id = :1 FOR UPDATE", (DEMO_ACCOUNT_ID,))
        account = dictfetchone(cursor)
        old_balance = Decimal(str(account['balance']))

        # Tentative uncommitted change
        cursor.execute("UPDATE bank_accounts SET balance = balance + 2000 WHERE account_id = :1", (DEMO_ACCOUNT_ID,))

        # Explicit ROLLBACK restores previous database state
        connection.rollback()
        log_audit("DEMO_ROLLBACK", "ACCOUNT", DEMO_ACCOUNT_ID, "Executed ROLLBACK demonstration")

        return render_success(
            "Transaction Rolled Back Completely",
            "An update of +INR 2,000.00 was tentatively applied in buffer cache, then immediately undone using ROLLBACK. Database remains unchanged.",
            old_balance=old_balance,
            new_balance=old_balance,
            transaction_status='ROLLED_BACK',
            back_url=back_url,
            back_label="Back to Transaction Control",
            transaction_demo=True
        )
    except Exception as e:
        connection.rollback()
        return render_error("Rollback Demo Failed", safe_error_message(e), back_url, "Back")
    finally:
        cursor.close()
        connection.close()


@app.route("/transaction-control/savepoint", methods=["POST"])
@app.route("/admin/transaction-control/savepoint", methods=["POST"])
@login_required
def demo_savepoint():
    role = session.get("role")
    cid = session.get("customer_id")
    is_demo = (cid == DEMO_ACCOUNT_ID or str(session.get("email", "")).lower() == "demo@kapabank.com")
    back_url = "/admin/transaction-control" if role == "ADMIN" else "/transaction-control"

    if not validate_csrf():
        return render_error("Security Error", "Invalid CSRF token.", back_url, "Back")

    if role != "ADMIN" and not is_demo:
        return render_error("Access Forbidden", "Only Administrator and the Demo Customer can execute TCL operations.", back_url, "Back")

    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT balance FROM bank_accounts WHERE account_id = :1 FOR UPDATE", (DEMO_ACCOUNT_ID,))
        account = dictfetchone(cursor)
        old_balance = Decimal(str(account['balance']))

        # Step 1: Add 1,000
        cursor.execute("UPDATE bank_accounts SET balance = balance + 1000 WHERE account_id = :1", (DEMO_ACCOUNT_ID,))

        # Step 2: Establish SAVEPOINT
        cursor.execute("SAVEPOINT intermediate_checkpoint")

        # Step 3: Add 2,000
        cursor.execute("UPDATE bank_accounts SET balance = balance + 2000 WHERE account_id = :1", (DEMO_ACCOUNT_ID,))

        # Step 4: Partial Rollback to SAVEPOINT
        cursor.execute("ROLLBACK TO SAVEPOINT intermediate_checkpoint")

        # Step 5: Record transaction for the retained first operation and COMMIT
        cursor.execute("INSERT INTO bank_transactions (account_id, transaction_type, amount, status) VALUES (:1, 'DEPOSIT', 1000, 'COMMITTED')", (DEMO_ACCOUNT_ID,))
        connection.commit()

        log_audit("DEMO_SAVEPOINT", "ACCOUNT", DEMO_ACCOUNT_ID, "Executed SAVEPOINT partial rollback demonstration")

        return render_success(
            "Partial Rollback to SAVEPOINT Successful",
            "Step 1 (+INR 1,000) was saved; Step 2 (+INR 2,000) was undone via ROLLBACK TO SAVEPOINT; remaining transaction was committed.",
            old_balance=old_balance,
            new_balance=old_balance + Decimal('1000'),
            transaction_status='COMMITTED',
            back_url=back_url,
            back_label="Back to Transaction Control",
            transaction_demo=True
        )
    except Exception as e:
        connection.rollback()
        return render_error("Savepoint Demo Failed", safe_error_message(e), back_url, "Back")
    finally:
        cursor.close()
        connection.close()


@app.route("/transaction-control/reset", methods=["POST"])
@app.route("/admin/transaction-control/reset", methods=["POST"])
@login_required
def demo_reset():
    role = session.get("role")
    cid = session.get("customer_id")
    is_demo = (cid == DEMO_ACCOUNT_ID or str(session.get("email", "")).lower() == "demo@kapabank.com")
    back_url = "/admin/transaction-control" if role == "ADMIN" else "/transaction-control"

    if not validate_csrf():
        return render_error("Security Error", "Invalid CSRF token.", back_url, "Back")

    if role != "ADMIN" and not is_demo:
        return render_error("Access Forbidden", "Only Administrator and the Demo Customer can execute TCL operations.", back_url, "Back")

    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT balance FROM bank_accounts WHERE account_id = :1 FOR UPDATE", (DEMO_ACCOUNT_ID,))
        cursor.execute("UPDATE bank_accounts SET balance = 10000 WHERE account_id = :1", (DEMO_ACCOUNT_ID,))
        cursor.execute("DELETE FROM bank_transactions WHERE account_id = :1", (DEMO_ACCOUNT_ID,))
        connection.commit()

        log_audit("DEMO_RESET", "ACCOUNT", DEMO_ACCOUNT_ID, "Reset demo account balance to 10000")

        return render_success(
            "Demo Account Reset Complete",
            "The demo account balance has been restored to INR 10,000.00 and all prior demonstration transactions were purged.",
            transaction_demo=True,
            back_url=back_url,
            back_label="Back to Transaction Control"
        )
    except Exception as e:
        connection.rollback()
        return render_error("Reset Failed", safe_error_message(e), back_url, "Back")
    finally:
        cursor.close()
        connection.close()


@app.route("/admin/statements/download/pdf/<int:account_id>")
@admin_required
def admin_download_pdf_statement(account_id):
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            SELECT a.account_id, a.customer_id, a.account_number, a.account_type, a.balance, a.status,
                   c.name, c.email, c.phone, c.address
            FROM bank_accounts a
            JOIN customers c ON a.customer_id = c.customer_id
            WHERE a.account_id = :1
        """, (account_id,))
        record = dictfetchone(cursor)

        if not record:
            return render_error("Not Found", "Account record does not exist.", "/admin/accounts", "Back to Accounts")

        customer = {
            "name": record['name'],
            "email": record['email'],
            "phone": record['phone'],
            "address": record['address']
        }
        account = {
            "account_number": record['account_number'],
            "account_type": record['account_type'],
            "balance": record['balance'],
            "status": record['status']
        }

        cursor.execute("""
            SELECT transaction_id, transaction_type, amount,
                TO_CHAR(FROM_TZ(transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'DD-MM-YYYY') AS display_date,
                TO_CHAR(FROM_TZ(transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'HH12:MI AM') AS display_time,
                status
            FROM bank_transactions
            WHERE account_id = :1
            ORDER BY transaction_date DESC
        """, (account_id,))
        transactions = dictfetchall(cursor)

        pdf_bytes = generate_pdf_statement(customer, account, transactions)

        log_audit("ADMIN_STATEMENT_PDF", "ACCOUNT", account_id, f"Admin generated PDF statement for {account['account_number']}")

        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=KAPA_Admin_Statement_{account["account_number"]}.pdf'
        return response

    except Exception as e:
        logger.error("Admin PDF download error: %s", str(e), exc_info=True)
        return render_error("Export Error", "Failed to generate PDF statement.", "/admin/accounts", "Back")
    finally:
        cursor.close()
        connection.close()


@app.route("/admin/statements/download/csv/<int:account_id>")
@admin_required
def admin_download_csv_statement(account_id):
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            SELECT a.account_id, a.customer_id, a.account_number, a.account_type, a.balance, a.status,
                   c.name, c.email, c.phone, c.address
            FROM bank_accounts a
            JOIN customers c ON a.customer_id = c.customer_id
            WHERE a.account_id = :1
        """, (account_id,))
        record = dictfetchone(cursor)

        if not record:
            return render_error("Not Found", "Account record does not exist.", "/admin/accounts", "Back to Accounts")

        customer = {
            "name": record['name'],
            "email": record['email'],
            "phone": record['phone'],
            "address": record['address']
        }
        account = {
            "account_number": record['account_number'],
            "account_type": record['account_type'],
            "balance": record['balance'],
            "status": record['status']
        }

        cursor.execute("""
            SELECT transaction_id, transaction_type, amount,
                TO_CHAR(FROM_TZ(transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'DD-MM-YYYY') AS display_date,
                TO_CHAR(FROM_TZ(transaction_date, 'UTC') AT TIME ZONE 'Asia/Kolkata', 'HH12:MI AM') AS display_time,
                status
            FROM bank_transactions
            WHERE account_id = :1
            ORDER BY transaction_date DESC
        """, (account_id,))
        transactions = dictfetchall(cursor)

        csv_content = generate_csv_statement(customer, account, transactions)

        log_audit("ADMIN_STATEMENT_CSV", "ACCOUNT", account_id, f"Admin exported CSV statement for {account['account_number']}")

        response = make_response(csv_content)
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=KAPA_Admin_Transactions_{account["account_number"]}.csv'
        return response

    except Exception as e:
        logger.error("Admin CSV export error: %s", str(e), exc_info=True)
        return render_error("Export Error", "Failed to export CSV statement.", "/admin/accounts", "Back")
    finally:
        cursor.close()
        connection.close()


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(400)
def bad_request(e):
    return render_error("Bad Request (400)", "The server could not understand your request. Please ensure valid form submission.", "/", "Dashboard"), 400

@app.errorhandler(403)
def forbidden(e):
    return render_error("Forbidden (403)", "You do not have permission to access the requested resource.", "/", "Dashboard"), 403

@app.errorhandler(404)
def page_not_found(e):
    return render_error("Page Not Found (404)", "The page you are looking for does not exist.", "/", "Dashboard"), 404

@app.errorhandler(500)
def server_error(e):
    logger.error("500 Internal Server Error: %s", str(e), exc_info=True)
    return render_error("Server Error (500)", "An unexpected server condition occurred. Our technical staff has been notified.", "/", "Dashboard"), 500


if __name__ == '__main__':
    port = int(os.getenv("PORT", 5001))
    app.run(debug=True, host="127.0.0.1", port=port)