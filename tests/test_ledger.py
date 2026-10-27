import sqlite3

import pytest

from app import database
from app.services import transfer_money


def test_create_and_retrieve_account(client):
    response = client.post("/accounts", json={"name": "  Nimesh  "})
    assert response.status_code == 201
    account = response.json()

    assert account["name"] == "Nimesh"
    assert account["balance"] == 0
    assert account["id"]
    assert account["created_at"]
    assert client.get(f"/accounts/{account['id']}").json() == account
    assert client.get(f"/accounts/{account['id']}/balance").json() == {
        "account_id": account["id"],
        "balance": 0,
    }


def test_list_accounts_includes_account_ids(client, account):
    response = client.get("/accounts")

    assert response.status_code == 200
    assert any(item["id"] == account["id"] for item in response.json())


def test_account_creation_rejects_blank_name_and_client_balance(client):
    assert client.post("/accounts", json={"name": "   "}).status_code == 422
    assert client.post(
        "/accounts", json={"name": "Nimesh", "balance": 5000}
    ).status_code == 422
    assert client.get("/accounts").json() == []


def test_credit_updates_balance_and_allows_reference_on_another_account(
    client, account
):
    request = {
        "amount": 5000,
        "reference_id": "payment-001",
        "description": "First payment",
    }
    response = client.post(f"/accounts/{account['id']}/credits", json=request)

    assert response.status_code == 201
    assert response.json()["type"] == "credit"
    assert client.get(f"/accounts/{account['id']}/balance").json()["balance"] == 5000

    second_account = client.post("/accounts", json={"name": "Asha"}).json()
    response = client.post(
        f"/accounts/{second_account['id']}/credits", json=request
    )
    assert response.status_code == 201


def test_debit_and_insufficient_balance_record_failed_attempt(client, account):
    url = f"/accounts/{account['id']}"
    client.post(
        f"{url}/credits",
        json={"amount": 5000, "reference_id": "funding"},
    )

    debit = client.post(
        f"{url}/debits",
        json={"amount": 2000, "reference_id": "debit-001"},
    )
    assert debit.status_code == 201
    assert client.get(f"{url}/balance").json()["balance"] == 3000

    rejected = client.post(
        f"{url}/debits",
        json={"amount": 4000, "reference_id": "debit-002"},
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == "Insufficient balance"
    assert client.get(f"{url}/balance").json()["balance"] == 3000

    connection = database.get_connection()
    try:
        attempt = connection.execute(
            """
            SELECT status, failure_reason, transaction_id
            FROM transaction_attempts WHERE reference_id = 'debit-002'
            """
        ).fetchone()
    finally:
        connection.close()
    assert attempt == ("failed", "Insufficient balance", None)


def test_duplicate_reference_does_not_change_balance_and_is_recorded(client, account):
    url = f"/accounts/{account['id']}/credits"
    request = {"amount": 1000, "reference_id": "same-payment"}
    assert client.post(url, json=request).status_code == 201
    duplicate = client.post(url, json=request)

    assert duplicate.status_code == 409
    assert client.get(f"/accounts/{account['id']}/balance").json()["balance"] == 1000

    connection = database.get_connection()
    try:
        attempts = connection.execute(
            "SELECT status FROM transaction_attempts WHERE reference_id = ? ORDER BY rowid",
            ("same-payment",),
        ).fetchall()
        transactions = connection.execute(
            "SELECT COUNT(*) FROM transactions WHERE account_id = ?",
            (account["id"],),
        ).fetchone()[0]
    finally:
        connection.close()
    assert attempts == [("success",), ("failed",)]
    assert transactions == 1


def test_history_filter_pagination_and_newest_first(client, account):
    account_id = account["id"]
    client.post(
        f"/accounts/{account_id}/credits",
        json={"amount": 1000, "reference_id": "credit-1"},
    )
    client.post(
        f"/accounts/{account_id}/debits",
        json={"amount": 200, "reference_id": "debit-1"},
    )
    client.post(
        f"/accounts/{account_id}/credits",
        json={"amount": 300, "reference_id": "credit-2"},
    )

    # Give each row a known timestamp so ordering is deterministic in this test.
    connection = database.get_connection()
    try:
        for reference_id, timestamp in [
            ("credit-1", "2026-01-01T00:00:00+00:00"),
            ("debit-1", "2026-01-02T00:00:00+00:00"),
            ("credit-2", "2026-01-03T00:00:00+00:00"),
        ]:
            connection.execute(
                "UPDATE transactions SET created_at = ? WHERE reference_id = ?",
                (timestamp, reference_id),
            )
        connection.commit()
    finally:
        connection.close()

    first_page = client.get(
        f"/accounts/{account_id}/transactions?page=1&limit=2"
    ).json()
    assert first_page["page"] == 1
    assert first_page["page_size"] == 2
    assert first_page["total_records"] == 3
    assert first_page["total_pages"] == 2
    assert [item["reference_id"] for item in first_page["transactions"]] == [
        "credit-2",
        "debit-1",
    ]

    credits = client.get(
        f"/accounts/{account_id}/transactions?type=credit"
    ).json()
    assert credits["total_records"] == 2
    assert all(item["type"] == "credit" for item in credits["transactions"])


def test_missing_account_and_invalid_history_parameters(client):
    assert client.get("/accounts/missing/balance").status_code == 404
    assert client.get("/accounts/missing/transactions").status_code == 404
    assert client.get("/accounts/missing/transactions?page=0").status_code == 422


def test_transfer_moves_money_and_writes_both_ledger_entries(client, account):
    source_id = account["id"]
    destination = client.post("/accounts", json={"name": "Asha"}).json()
    destination_id = destination["id"]
    client.post(
        f"/accounts/{source_id}/credits",
        json={"amount": 5000, "reference_id": "transfer-funding"},
    )

    response = client.post(
        "/transfers",
        json={
            "source_account_id": source_id,
            "destination_account_id": destination_id,
            "amount": 2000,
            "reference_id": "transfer-001",
            "description": "Pay Asha",
        },
    )

    assert response.status_code == 201
    result = response.json()
    assert result["source_transaction"]["type"] == "debit"
    assert result["destination_transaction"]["type"] == "credit"
    assert result["source_transaction"]["reference_id"] == "transfer-001"
    assert result["destination_transaction"]["reference_id"] == "transfer-001"
    assert client.get(f"/accounts/{source_id}/balance").json()["balance"] == 3000
    assert client.get(f"/accounts/{destination_id}/balance").json()["balance"] == 2000

    attempts = database.get_connection()
    try:
        rows = attempts.execute(
            """
            SELECT status, transaction_id FROM transaction_attempts
            WHERE reference_id = ? ORDER BY type
            """,
            ("transfer-001",),
        ).fetchall()
    finally:
        attempts.close()
    assert len(rows) == 2
    assert all(status == "success" and transaction_id for status, transaction_id in rows)


def test_transfer_rejects_insufficient_funds_and_records_failed_attempts(
    client, account
):
    source_id = account["id"]
    destination = client.post("/accounts", json={"name": "Asha"}).json()
    destination_id = destination["id"]
    client.post(
        f"/accounts/{source_id}/credits",
        json={"amount": 1000, "reference_id": "transfer-funding"},
    )

    response = client.post(
        "/transfers",
        json={
            "source_account_id": source_id,
            "destination_account_id": destination_id,
            "amount": 1500,
            "reference_id": "transfer-too-large",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Insufficient balance"
    assert client.get(f"/accounts/{source_id}/balance").json()["balance"] == 1000
    assert client.get(f"/accounts/{destination_id}/balance").json()["balance"] == 0
    attempts = database.get_connection()
    try:
        rows = attempts.execute(
            """
            SELECT status, failure_reason, transaction_id
            FROM transaction_attempts WHERE reference_id = ?
            """,
            ("transfer-too-large",),
        ).fetchall()
    finally:
        attempts.close()
    assert rows == [
        ("failed", "Insufficient balance", None),
        ("failed", "Insufficient balance", None),
    ]


def test_transfer_rejects_missing_account_and_duplicate_reference(client, account):
    source_id = account["id"]
    destination = client.post("/accounts", json={"name": "Asha"}).json()
    destination_id = destination["id"]
    client.post(
        f"/accounts/{source_id}/credits",
        json={"amount": 3000, "reference_id": "shared-reference"},
    )

    missing_destination = client.post(
        "/transfers",
        json={
            "source_account_id": source_id,
            "destination_account_id": "missing-account",
            "amount": 500,
            "reference_id": "missing-destination-transfer",
        },
    )
    assert missing_destination.status_code == 404
    assert client.get(f"/accounts/{source_id}/balance").json()["balance"] == 3000

    missing_source = client.post(
        "/transfers",
        json={
            "source_account_id": "missing-account",
            "destination_account_id": destination_id,
            "amount": 500,
            "reference_id": "missing-source-transfer",
        },
    )
    assert missing_source.status_code == 404
    assert client.get(f"/accounts/{destination_id}/balance").json()["balance"] == 0

    duplicate = client.post(
        "/transfers",
        json={
            "source_account_id": source_id,
            "destination_account_id": destination_id,
            "amount": 500,
            "reference_id": "shared-reference",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Transaction already exists"
    assert client.get(f"/accounts/{source_id}/balance").json()["balance"] == 3000
    assert client.get(f"/accounts/{destination_id}/balance").json()["balance"] == 0


def test_transfer_rolls_back_both_sides_if_second_ledger_insert_fails(client, account):
    source_id = account["id"]
    destination = client.post("/accounts", json={"name": "Asha"}).json()
    destination_id = destination["id"]
    client.post(
        f"/accounts/{source_id}/credits",
        json={"amount": 3000, "reference_id": "transfer-funding"},
    )

    connection = database.get_connection()
    try:
        connection.execute(
            f"""
            CREATE TRIGGER reject_destination_credit
            BEFORE INSERT ON transactions
            WHEN NEW.account_id = '{destination_id}' AND NEW.type = 'credit'
            BEGIN
                SELECT RAISE(ABORT, 'forced destination failure');
            END
            """
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(sqlite3.IntegrityError, match="forced destination failure"):
        transfer_money(source_id, destination_id, 1000, "transfer-atomicity")

    assert client.get(f"/accounts/{source_id}/balance").json()["balance"] == 3000
    assert client.get(f"/accounts/{destination_id}/balance").json()["balance"] == 0
    connection = database.get_connection()
    try:
        transaction_count = connection.execute(
            "SELECT COUNT(*) FROM transactions WHERE reference_id = ?",
            ("transfer-atomicity",),
        ).fetchone()[0]
        attempts = connection.execute(
            "SELECT status FROM transaction_attempts WHERE reference_id = ?",
            ("transfer-atomicity",),
        ).fetchall()
    finally:
        connection.close()
    assert transaction_count == 0
    assert attempts == [("failed",), ("failed",)]


def test_transfer_validates_amount_accounts_and_distinct_endpoints(client, account):
    other = client.post("/accounts", json={"name": "Asha"}).json()
    request = {
        "source_account_id": account["id"],
        "destination_account_id": other["id"],
        "amount": 0,
        "reference_id": "invalid-transfer",
    }
    assert client.post("/transfers", json=request).status_code == 422

    request["amount"] = 100
    request["destination_account_id"] = account["id"]
    response = client.post("/transfers", json=request)
    assert response.status_code == 422
    assert response.json()["detail"] == "Source and destination accounts must be different"
