import logging
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from .database import get_connection

logger = logging.getLogger(__name__)


def create_account(name: str):
    cleaned_name = name.strip()

    if cleaned_name == "":
        raise ValueError("Name is required")

    account = {
        "id": str(uuid4()),
        "name": cleaned_name,
        "balance": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    connection = get_connection()

    try:
        connection.execute(
            """
            INSERT INTO accounts (id, name, balance, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (account["id"], account["name"], account["balance"], account["created_at"]),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    return account


def get_accounts():
    connection = get_connection()
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT id, name, balance, created_at
            FROM accounts
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
    finally:
        connection.close()

    return [dict(row) for row in rows]


def get_account(account_id: str):
    connection = get_connection()
    connection.row_factory = sqlite3.Row

    try:
        row = connection.execute(
            """
            SELECT id, name, balance, created_at
            FROM accounts
            WHERE id = ?
            """,
            (account_id,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        raise ValueError("Account not found")

    return dict(row)


def get_account_balance(account_id: str):
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT balance FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        raise ValueError("Account not found")

    return {"account_id": account_id, "balance": row[0]}


def get_transaction_history(account_id: str, page: int = 1, limit: int = 10,
                            transaction_type: str | None = None):
    if page < 1:
        raise ValueError("Page must be at least 1")
    if limit < 1 or limit > 100:
        raise ValueError("Limit must be between 1 and 100")
    if transaction_type not in (None, "credit", "debit"):
        raise ValueError("Type must be credit or debit")

    connection = get_connection()
    connection.row_factory = sqlite3.Row
    try:
        account = connection.execute(
            "SELECT id FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if account is None:
            raise ValueError("Account not found")

        if transaction_type is None:
            where_sql = "WHERE account_id = ?"
            parameters = (account_id,)
        else:
            where_sql = "WHERE account_id = ? AND type = ?"
            parameters = (account_id, transaction_type)

        total_records = connection.execute(
            f"SELECT COUNT(*) FROM transactions {where_sql}", parameters
        ).fetchone()[0]
        offset = (page - 1) * limit
        rows = connection.execute(
            f"""
            SELECT id, account_id, type, amount, description, reference_id, created_at
            FROM transactions
            {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (*parameters, limit, offset),
        ).fetchall()
    finally:
        connection.close()

    return {
        "account_id": account_id,
        "page": page,
        "page_size": limit,
        "total_records": total_records,
        "total_pages": (total_records + limit - 1) // limit,
        "transactions": [dict(row) for row in rows],
    }


def save_attempt(connection, transaction, status, failure_reason=None):
    connection.execute(
        """
        INSERT INTO transaction_attempts
            (id, account_id, type, amount, description, reference_id,
             status, failure_reason, transaction_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()), transaction["account_id"], transaction["type"],
            transaction["amount"], transaction["description"],
            transaction["reference_id"], status, failure_reason,
            transaction["id"] if status == "success" else None,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def add_transaction(account_id: str, transaction_type: str, amount: int,
                    reference_id: str, description: str = ""):
    if transaction_type not in ("credit", "debit"):
        raise ValueError("Transaction type must be credit or debit")
    # Amounts are whole paise, so 100 represents one rupee.
    if type(amount) is not int or amount <= 0:
        raise ValueError("Amount must be a positive whole number of paise")
    if not isinstance(reference_id, str) or not reference_id.strip():
        raise ValueError("Reference ID is required")
    if not isinstance(description, str):
        raise TypeError("Description must be text")

    transaction = {
        "id": str(uuid4()),
        "account_id": account_id,
        "type": transaction_type,
        "amount": amount,
        "description": description,
        "reference_id": reference_id.strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    connection = get_connection()
    try:
        # Reserve SQLite's writer before checking and changing account data.
        connection.execute("BEGIN IMMEDIATE")
        account = connection.execute(
            "SELECT balance FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if account is None:
            raise ValueError("Account not found")

        existing = connection.execute(
            "SELECT id FROM transactions WHERE account_id = ? AND reference_id = ?",
            (account_id, transaction["reference_id"]),
        ).fetchone()
        if existing is not None:
            raise ValueError("Transaction already exists")

        if transaction_type == "debit" and account[0] < amount:
            raise ValueError("Insufficient balance")

        connection.execute(
            """
            INSERT INTO transactions
                (id, account_id, type, amount, description, reference_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transaction["id"], account_id, transaction_type, amount, description,
                transaction["reference_id"], transaction["created_at"],
            ),
        )
        balance_change = amount if transaction_type == "credit" else -amount
        connection.execute(
            "UPDATE accounts SET balance = balance + ? WHERE id = ?",
            (balance_change, account_id),
        )
        save_attempt(connection, transaction, "success")
        connection.commit()
    except Exception as error:
        connection.rollback()
        # Save the failed attempt in a new database transaction after rollback.
        try:
            save_attempt(connection, transaction, "failed", str(error))
            connection.commit()
        except Exception:
            connection.rollback()
            logger.exception("Could not save failed transaction attempt")
        raise
    finally:
        connection.close()

    return transaction


def credit_account(account_id: str, amount: int, reference_id: str, description: str = ""):
    return add_transaction(account_id, "credit", amount, reference_id, description)


def debit_account(account_id: str, amount: int, reference_id: str, description: str = ""):
    return add_transaction(account_id, "debit", amount, reference_id, description)


def transfer_money(
    source_account_id: str,
    destination_account_id: str,
    amount: int,
    reference_id: str,
    description: str = "",
):
    if type(amount) is not int or amount <= 0:
        raise ValueError("Amount must be a positive whole number of paise")
    if not isinstance(reference_id, str) or not reference_id.strip():
        raise ValueError("Reference ID is required")
    if not isinstance(description, str):
        raise TypeError("Description must be text")
    if source_account_id == destination_account_id:
        raise ValueError("Source and destination accounts must be different")

    reference_id = reference_id.strip()
    created_at = datetime.now(timezone.utc).isoformat()
    debit = {
        "id": str(uuid4()),
        "account_id": source_account_id,
        "type": "debit",
        "amount": amount,
        "description": description,
        "reference_id": reference_id,
        "created_at": created_at,
    }
    credit = {
        "id": str(uuid4()),
        "account_id": destination_account_id,
        "type": "credit",
        "amount": amount,
        "description": description,
        "reference_id": reference_id,
        "created_at": created_at,
    }
    transfer_transactions = (debit, credit)

    connection = get_connection()
    try:
        # Lock writes while checking both accounts and applying both sides.
        connection.execute("BEGIN IMMEDIATE")
        source = connection.execute(
            "SELECT balance FROM accounts WHERE id = ?", (source_account_id,)
        ).fetchone()
        destination = connection.execute(
            "SELECT balance FROM accounts WHERE id = ?", (destination_account_id,)
        ).fetchone()
        if source is None or destination is None:
            raise ValueError("Account not found")

        for transaction in transfer_transactions:
            existing = connection.execute(
                """
                SELECT id FROM transactions
                WHERE account_id = ? AND reference_id = ?
                """,
                (transaction["account_id"], reference_id),
            ).fetchone()
            if existing is not None:
                raise ValueError("Transaction already exists")

        if source[0] < amount:
            raise ValueError("Insufficient balance")

        # Every write below is covered by this connection's single transaction.
        for transaction in transfer_transactions:
            connection.execute(
                """
                INSERT INTO transactions
                    (id, account_id, type, amount, description, reference_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transaction["id"],
                    transaction["account_id"],
                    transaction["type"],
                    transaction["amount"],
                    transaction["description"],
                    transaction["reference_id"],
                    transaction["created_at"],
                ),
            )

        connection.execute(
            "UPDATE accounts SET balance = balance - ? WHERE id = ?",
            (amount, source_account_id),
        )
        connection.execute(
            "UPDATE accounts SET balance = balance + ? WHERE id = ?",
            (amount, destination_account_id),
        )
        for transaction in transfer_transactions:
            save_attempt(connection, transaction, "success")
        connection.commit()
    except Exception as error:
        connection.rollback()
        # Keep a record of the failed transfer after rolling back its money changes.
        try:
            for transaction in transfer_transactions:
                save_attempt(connection, transaction, "failed", str(error))
            connection.commit()
        except Exception:
            connection.rollback()
            logger.exception("Could not save failed transfer attempts")
        raise
    finally:
        connection.close()

    return {
        "source_transaction": debit,
        "destination_transaction": credit,
    }


