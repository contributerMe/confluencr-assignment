from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .database import initialize_database
from .services import (
    create_account,
    credit_account,
    debit_account,
    get_account,
    get_account_balance,
    get_accounts,
    get_transaction_history,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Transaction Ledger API", lifespan=lifespan)


class CreateAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1)


class TransactionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    amount: int = Field(gt=0, strict=True, description="Amount in paise: 5000 means INR 50")
    reference_id: str = Field(min_length=1)
    description: str = ""


@app.get("/")
def home():
    return {"message": "Our ledger API is running!"}


@app.post("/accounts", status_code=201)
def create_account_endpoint(request: CreateAccountRequest):
    try:
        return create_account(request.name)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/accounts")
def get_accounts_endpoint():
    return get_accounts()


@app.get("/accounts/{account_id}")
def get_account_endpoint(account_id: str):
    try:
        return get_account(account_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/accounts/{account_id}/balance")
def get_account_balance_endpoint(account_id: str):
    try:
        return get_account_balance(account_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/accounts/{account_id}/transactions")
def transaction_history_endpoint(
    account_id: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=100),
    type: str | None = Query(default=None, pattern="^(credit|debit)$"),
):
    try:
        return get_transaction_history(account_id, page, limit, type)
    except ValueError as error:
        status_code = 404 if str(error) == "Account not found" else 422
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@app.post("/accounts/{account_id}/credits", status_code=201)
def credit_account_endpoint(account_id: str, request: TransactionRequest):
    try:
        return credit_account(
            account_id, request.amount, request.reference_id, request.description
        )
    except ValueError as error:
        if str(error) == "Account not found":
            status_code = 404
        elif str(error) == "Transaction already exists":
            status_code = 409
        else:
            status_code = 422
        raise HTTPException(status_code=status_code, detail=str(error)) from error


@app.post("/accounts/{account_id}/debits", status_code=201)
def debit_account_endpoint(account_id: str, request: TransactionRequest):
    try:
        return debit_account(
            account_id, request.amount, request.reference_id, request.description
        )
    except ValueError as error:
        if str(error) == "Account not found":
            status_code = 404
        elif str(error) in ("Transaction already exists", "Insufficient balance"):
            status_code = 409
        else:
            status_code = 422
        raise HTTPException(status_code=status_code, detail=str(error)) from error
