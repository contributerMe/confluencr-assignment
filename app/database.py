import sqlite3
from pathlib import Path


DATABASE_PATH = Path(__file__).resolve().parent.parent / "ledger.db"


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database():
    connection = get_connection()

    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL CHECK (length(trim(name)) > 0),
                balance INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0),
                created_at TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES accounts(id),
                type TEXT NOT NULL CHECK (type IN ('credit', 'debit')),
                amount INTEGER NOT NULL
                    CHECK (typeof(amount) = 'integer' AND amount > 0),
                description TEXT NOT NULL,
                reference_id TEXT NOT NULL CHECK (length(trim(reference_id)) > 0),
                created_at TEXT NOT NULL,
                UNIQUE (account_id, reference_id)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS transaction_attempts (
                id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('credit', 'debit')),
                amount INTEGER NOT NULL
                    CHECK (typeof(amount) = 'integer' AND amount > 0),
                description TEXT NOT NULL,
                reference_id TEXT NOT NULL CHECK (length(trim(reference_id)) > 0),
                status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
                failure_reason TEXT,
                transaction_id TEXT REFERENCES transactions(id),
                created_at TEXT NOT NULL,
                CHECK (
                    (status = 'success' AND transaction_id IS NOT NULL
                        AND failure_reason IS NULL)
                    OR
                    (status = 'failed' AND transaction_id IS NULL
                        AND failure_reason IS NOT NULL)
                )
            )
        """)
        connection.commit()
    finally:
        connection.close()


