# PayStack Payment Verification Guide

This guide demonstrates how to implement payment verification with PayStack using our API.

## Backend Implementation

The backend provides an endpoint to verify payment status using the PayStack API and update user subscriptions:

```
GET /payments/check-subscription?reference={reference}&user_id={user_id}
```

Parameters:
- `reference`: The payment reference ID returned by PayStack after a payment attempt
- `user_id`: The UUID of the user making the payment (required for updating subscription status)

## Subscription Plans

The API supports two subscription plans:
1. STARTER Plan: NGN 300.50 (30,050 kobo)
2. PRO Plan: NGN 403.33 (40,333 kobo)

The plan is automatically determined based on the payment amount.

## Frontend Implementation Example

Here's how to implement payment verification in your frontend code:

### Using Fetch API (JavaScript)

```javascript
// After initiating payment with PayStack, you'll receive a reference
// Use this reference to verify the payment status
async function verifyPayment(reference, userId) {
  try {
    const response = await fetch(`/api/payments/check-subscription?reference=${reference}&user_id=${userId}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });
    
    const result = await response.json();
    
    if (result.success) {
      // Payment successful - handle accordingly
      console.log('Payment verified successfully:', result.data);
      
      // Update UI or redirect user
      showSuccessMessage(`${result.data.amount / 100}`); // Amount is in kobo (100 kobo = 1 NGN)
      
      // The backend will automatically:
      // 1. Update user's payment status to PRO or STARTER
      // 2. Create a subscription record
      // 3. Set subscription end date
      
      // You might want to refresh user data or redirect to dashboard
      await refreshUserData();
      redirectToDashboard();
    } else {
      // Payment verification failed
      console.error('Payment verification failed:', result.message);
      showErrorMessage(result.message);
    }
    
    return result;
  } catch (error) {
    console.error('Error verifying payment:', error);
    showErrorMessage('Failed to verify payment. Please try again.');
    return { success: false, message: error.message };
  }
}

// Example usage with PayStack standard integration
function payWithPaystack(email, amount, userId) {
  const handler = PaystackPop.setup({
    key: 'YOUR_PUBLIC_KEY', // Replace with your PayStack public key
    email: email,
    amount: amount * 100, // Convert to kobo (smallest currency unit in NGN)
    currency: 'NGN',
    ref: generateReference(), // Function to generate unique reference
    callback: function(response) {
      // This is called after the payment is completed
      const reference = response.reference;
      verifyPayment(reference, userId);
    },
    onClose: function() {
      // Handle when the PayStack modal is closed
      alert('Payment window closed.');
    }
  });
  handler.openIframe();
}

// Generate a unique reference ID
function generateReference() {
  const timestamp = new Date().getTime();
  const randomStr = Math.random().toString(36).substring(2, 15);
  return `ref-${timestamp}-${randomStr}`;
}
```

### Using Axios (JavaScript)

```javascript
// Using Axios
import axios from 'axios';

async function verifyPayment(reference, userId) {
  try {
    const { data } = await axios.get(`/api/payments/check-subscription?reference=${reference}&user_id=${userId}`);
    
    if (data.success) {
      // Payment successful
      console.log('Payment verified:', data.data);
      // Update UI with success message
      // The backend will automatically update subscription status
    } else {
      // Payment verification failed
      console.error('Verification failed:', data.message);
      // Show error message to user
    }
    
    return data;
  } catch (error) {
    console.error('Error verifying payment:', error);
    return { success: false, message: error.message };
  }
}
```

## Important Notes

1. Always verify payments on your backend, never trust client-side verification alone.
2. The PayStack secret key should only be used on the backend and never exposed to the frontend.
3. Store successful payment information in your database for record-keeping and to prevent duplicate payments.
4. Consider implementing webhooks for more reliable payment notifications.
5. The backend automatically:
   - Updates the user's payment status in users_metadata table
   - Creates a subscription record in the subscriptions table
   - Sets appropriate start and end dates for the subscription
   - Handles different subscription plans based on the payment amount

## Response Structure

A successful verification will return:

```json
{
  "success": true,
  "message": "Payment verified and PRO subscription activated successfully",
  "data": {
    "id": 1234567890,
    "status": "success",
    "reference": "your-reference",
    "amount": 40333,
    "currency": "NGN",
    // Additional payment details...
  }
}
```

A failed verification will return:

```json
{
  "success": false,
  "message": "Error message explaining the failure",
  "data": null
}
```

## Database Updates

When a payment is successfully verified, the following updates occur:

1. users_metadata table:
   - payment_status: Updated to "PRO" or "STARTER"
   - updated_at: Set to current timestamp

2. subscriptions table:
   - New record created with:
     - user_id: The user's UUID
     - plan_name: "PRO" or "STARTER"
     - price: Payment amount in NGN
     - billing_cycle: "monthly"
     - status: "active"
     - start_date: Current timestamp
     - end_date: 30 days from start_date
     - payment_reference: PayStack reference ID 