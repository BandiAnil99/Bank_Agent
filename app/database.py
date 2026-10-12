from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app import config


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(config.DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS customers (
                customer_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS accounts (
                account_id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id TEXT NOT NULL REFERENCES customers(customer_id),
                account_number TEXT NOT NULL UNIQUE,
                account_type TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS loan_applications (
                application_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL REFERENCES customers(customer_id),
                loan_amount REAL NOT NULL,
                tenure_months INTEGER NOT NULL,
                annual_interest_rate REAL NOT NULL,
                monthly_salary REAL NOT NULL,
                existing_monthly_emi REAL NOT NULL,
                calculated_emi REAL NOT NULL,
                eligibility_json TEXT NOT NULL,
                status TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                confirmation_token_hash TEXT NOT NULL,
                confirmation_expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(customer_id, idempotency_key)
            );
            """
        )
        connection.executemany(
            "INSERT OR IGNORE INTO customers (customer_id, display_name) VALUES (?, ?)",
            [("customer-001", "Asha Rao"), ("customer-002", "Ravi Kumar")],
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO accounts
                (customer_id, account_number, account_type, status)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("customer-001", "100012345678", "savings", "active"),
                ("customer-002", "200098765432", "current", "active"),
            ],
        )
