import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

@pytest.mark.asyncio
@patch("app.core.supabase_client.supabase.table")
@patch("httpx.AsyncClient.get")
async def test_check_subscription_success(mock_get, mock_supabase_table):
    # Mock Supabase responses
    mock_update = AsyncMock()
    mock_update.execute = AsyncMock(return_value={"data": None})
    mock_insert = AsyncMock()
    mock_insert.execute = AsyncMock(return_value={"data": None})
    
    mock_table = AsyncMock()
    mock_table.update.return_value.eq.return_value = mock_update
    mock_table.insert.return_value = mock_insert
    
    mock_supabase_table.return_value = mock_table

    # Mock the httpx response
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": True,
        "message": "Verification successful",
        "data": {
            "id": 4099260516,
            "status": "success",
            "reference": "test123",
            "amount": 40333,  # PRO plan amount
            "gateway_response": "Successful",
            "paid_at": "2024-08-22T09:15:02.000Z",
            "created_at": "2024-08-22T09:14:24.000Z",
            "channel": "card",
            "currency": "NGN",
            "log": {
                "start_time": 1724318098,
                "time_spent": 4,
                "attempts": 1,
                "errors": 0,
                "success": True,
                "mobile": False,
                "input": [],
                "history": []
            },
            "fees": 10283,
            "authorization": {
                "authorization_code": "AUTH_test",
                "bin": "408408",
                "last4": "4081",
                "exp_month": "12",
                "exp_year": "2030",
                "channel": "card",
                "card_type": "visa",
                "bank": "TEST BANK",
                "country_code": "NG",
                "brand": "visa",
                "reusable": True,
                "signature": "SIG_test"
            },
            "customer": {
                "id": 181873746,
                "email": "test@example.com",
                "customer_code": "CUS_test",
                "risk_action": "default"
            },
            "paidAt": "2024-08-22T09:15:02.000Z",
            "createdAt": "2024-08-22T09:14:24.000Z",
            "requested_amount": 40333,
            "transaction_date": "2024-08-22T09:14:24.000Z",
            "plan_object": {},
            "subaccount": {},
            "split": {},
            "metadata": "",
            "ip_address": "127.0.0.1"
        }
    }
    mock_get.return_value = mock_response

    # Test the endpoint with user_id
    test_user_id = "123e4567-e89b-12d3-a456-426614174000"
    response = client.get(f"/payments/check-subscription?reference=test123&user_id={test_user_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True
    assert "PRO subscription activated successfully" in data["message"]
    assert data["data"]["reference"] == "test123"
    assert data["data"]["status"] == "success"

    # Verify Supabase calls
    mock_supabase_table.assert_any_call("users_metadata")
    mock_supabase_table.assert_any_call("subscriptions")
    assert mock_table.update.called
    assert mock_table.insert.called

@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_check_subscription_failure(mock_get):
    # Mock a failed response
    mock_response = AsyncMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {
        "status": False,
        "message": "Invalid reference"
    }
    mock_get.return_value = mock_response

    # Test the endpoint with user_id
    test_user_id = "123e4567-e89b-12d3-a456-426614174000"
    response = client.get(f"/payments/check-subscription?reference=invalid_ref&user_id={test_user_id}")
    
    assert response.status_code == 200  # The API still returns 200 but with success=False
    data = response.json()
    assert data["success"] == False
    assert "Invalid reference" in data["message"]
    assert data["data"] is None

@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_check_subscription_invalid_amount(mock_get):
    # Mock response with invalid amount
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": True,
        "message": "Verification successful",
        "data": {
            "status": "success",
            "reference": "test123",
            "amount": 12345,  # Invalid amount that doesn't match any plan
            "currency": "NGN"
        }
    }
    mock_get.return_value = mock_response

    # Test the endpoint
    test_user_id = "123e4567-e89b-12d3-a456-426614174000"
    response = client.get(f"/payments/check-subscription?reference=test123&user_id={test_user_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] == False
    assert "Invalid payment amount" in data["message"] 