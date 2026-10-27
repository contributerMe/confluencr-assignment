# Transaction Ledger API

[![Tests](https://github.com/contributerMe/confluencr-assignment/actions/workflows/tests.yml/badge.svg)](https://github.com/contributerMe/confluencr-assignment/actions/workflows/tests.yml)
[![Code Quality](https://github.com/contributerMe/confluencr-assignment/actions/workflows/code-quality.yml/badge.svg)](https://github.com/contributerMe/confluencr-assignment/actions/workflows/code-quality.yml)

A beginner-friendly Python backend for creating accounts, recording credits and debits, and retrieving balances and transaction history.

## Requirements

- Python 3.10 or newer
- pip

## Run locally

Open a terminal in this project folder and create a virtual environment:

```bash
python3 -m venv .venv
```

Activate it on macOS or Linux:

```bash
source .venv/bin/activate
```

On Windows PowerShell, use:

```powershell
.venv\Scripts\Activate.ps1
```

Install the project dependencies and start the API:

```bash
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

The API is available at <http://127.0.0.1:8000>. Interactive API documentation is at <http://127.0.0.1:8000/docs>.

The SQLite database is created as `ledger.db` in the project folder when the API starts. Account and transaction data persist between runs.

## Tests and code quality

Install the development dependencies in the active virtual environment:

```bash
python -m pip install -r requirements-dev.txt
```

Install the Git pre-commit hook once in this repository:

```bash
pre-commit install
```

Before each commit, the hook runs Ruff and applies safe fixes automatically. If it changes a file, add that changed file and commit again.

Run the test suite, lint check, and Python syntax check:

```bash
python -m pytest
ruff check app tests
python -m compileall -q app tests
```

The test suite covers account creation and lookup, balance reads, credits, debits, duplicate references, failed attempts, and transaction history filtering and pagination. Latest local results: **8 tests passed** and Python syntax compilation passed. GitHub Actions runs the tests and code quality checks on each push and pull request.

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/accounts` | Create an account with an initial balance of zero |
| `GET` | `/accounts` | List all accounts, including their IDs |
| `GET` | `/accounts/{account_id}` | Get account details |
| `GET` | `/accounts/{account_id}/balance` | Get the current balance |
| `POST` | `/accounts/{account_id}/credits` | Add a credit |
| `POST` | `/accounts/{account_id}/debits` | Add a debit if funds are sufficient |
| `GET` | `/accounts/{account_id}/transactions` | Get newest-first transaction history |

### Creating an account

Send `POST /accounts` with:

```json
{"name": "Nimesh"}
```

The API generates the account ID and creation time. Clients cannot set the starting balance.

### Adding a credit or debit

Send a request to the account's `/credits` or `/debits` path with:

```json
{
  "amount": 5000,
  "reference_id": "payment-001",
  "description": "Example payment"
}
```

Amounts are positive whole numbers of paise: `5000` means ₹50. A reference ID can be used only once per account. Repeated references and debits with insufficient funds are rejected.

### Transaction history

`GET /accounts/{account_id}/transactions` accepts optional query parameters:

- `page`: starts at 1; defaults to 1.
- `limit`: records per page; defaults to 10 and cannot exceed 100.
- `type`: `credit` or `debit`; omit it to include both.

For example: `/accounts/ACCOUNT_ID/transactions?page=2&limit=10&type=debit`.

The response includes the page number, page size, total records, total pages, and the transaction rows. Invalid query parameters return a validation error.

## Data and consistency

- `accounts` stores each account and its current balance.
- `transactions` stores successful credits and debits. These records are the account's money movement history.
- `transaction_attempts` records valid processing attempts as `success` or `failed`, including a reason for failures. A failed attempt does not change the balance or create a successful transaction.
- The successful transaction and balance update are committed together. If either operation fails, both are rolled back; the failed attempt is then saved separately.
- Duplicate reference IDs are rejected for the same account. The same reference can be used by a different account.

## Assumptions

- This is a learning project and uses SQLite for local persistence.
- Amounts are stored as integer paise to avoid decimal rounding errors.
- Invalid request data is rejected before an attempt is recorded. Attempts are recorded when processing begins with a valid account ID value, amount, reference, and description.
- Transaction history contains successful transactions only; failed attempts are kept separately for auditability.
- Money transfer is an optional assignment bonus and has not been implemented yet.
