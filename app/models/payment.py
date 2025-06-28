from pydantic import BaseModel
from typing import Optional, Dict, List, Any, Union
from datetime import datetime

class PayStackLog(BaseModel):
    start_time: int
    time_spent: int
    attempts: int
    errors: int
    success: bool
    mobile: bool
    input: List[Any]
    history: List[Dict[str, Any]]

class PayStackAuthorization(BaseModel):
    authorization_code: str
    bin: str
    last4: str
    exp_month: str
    exp_year: str
    channel: str
    card_type: str
    bank: str
    country_code: str
    brand: str
    reusable: bool
    signature: str
    account_name: Optional[str] = None

class PayStackCustomer(BaseModel):
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: str
    customer_code: str
    phone: Optional[str] = None
    metadata: Optional[Any] = None
    risk_action: str
    international_format_phone: Optional[str] = None

class PayStackData(BaseModel):
    id: int
    domain: str
    status: str
    reference: str
    receipt_number: Optional[str] = None
    amount: int
    message: Optional[str] = None
    gateway_response: str
    paid_at: str
    created_at: str
    channel: str
    currency: str
    ip_address: str
    metadata: Any
    log: PayStackLog
    fees: int
    fees_split: Optional[Any] = None
    authorization: PayStackAuthorization
    customer: PayStackCustomer
    plan: Optional[Any] = None
    split: Dict[str, Any] = {}
    order_id: Optional[Any] = None
    paidAt: str
    createdAt: str
    requested_amount: int
    pos_transaction_data: Optional[Any] = None
    source: Optional[Any] = None
    fees_breakdown: Optional[Any] = None
    connect: Optional[Any] = None
    transaction_date: str
    plan_object: Dict[str, Any] = {}
    subaccount: Dict[str, Any] = {}

class PayStackResponse(BaseModel):
    status: bool
    message: str
    data: PayStackData

class CheckSubscriptionResponse(BaseModel):
    success: bool
    message: str
    data: Optional[PayStackData] = None

# New models used by /payments endpoints

class PaymentMethodResponse(BaseModel):
    id: str
    provider: str
    last_four: str
    card_type: str | None = None
    exp_month: int | None = None
    exp_year: int | None = None
    is_default: bool = False
    created_at: datetime | None = None

class PaymentMethodCreate(BaseModel):
    last_four: str
    card_type: str | None = None
    exp_month: int | None = None
    exp_year: int | None = None
    is_default: bool = True

class InvoiceResponse(BaseModel):
    id: str
    invoice_number: str | None = None
    amount: float
    currency: str
    status: str
    invoice_date: datetime
    due_date: datetime | None = None
    payment_date: datetime | None = None
    description: str | None = None 