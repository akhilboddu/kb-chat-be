# Gmail OAuth Integration Setup

This guide explains how to set up Gmail OAuth integration for follow-up automation in your chatbot system.

## Prerequisites

1. **Google Cloud Project**: You need a Google Cloud project with Gmail API enabled
2. **OAuth 2.0 Credentials**: Web application credentials from Google Cloud Console
3. **Database**: PostgreSQL/Supabase database access

## Setup Steps

### 1. Google Cloud Console Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select or create a project
3. Enable the Gmail API:
   - Go to "APIs & Services" > "Library"
   - Search for "Gmail API"
   - Click "Enable"

4. Create OAuth 2.0 credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth 2.0 Client ID"
   - Choose "Web application"
   - Add authorized redirect URIs:
     - `https://yourdomain.com/gmail-oauth-callback`
     - `http://localhost:3000/gmail-oauth-callback` (for development)

5. Note down your Client ID and Client Secret

### 2. Environment Variables

Add these environment variables to your backend `.env` file:

```bash
# Gmail OAuth Configuration
GOOGLE_CLIENT_ID=your_google_client_id_here
GOOGLE_CLIENT_SECRET=your_google_client_secret_here
```

### 3. Database Migration

Run the database migration to create the `gmail_configs` table:

```bash
cd kb-chat-be
python scripts/migrate_gmail_configs.py
```

### 4. Install Dependencies

The required Python packages should already be in `requirements.txt`. If not, install them:

```bash
pip install google-auth google-auth-oauthlib google-api-python-client
```

### 5. Frontend Setup

The frontend integration is already included in the EditBot component. The Gmail connection button will appear in the Follow-Up tool configuration.

## Usage

### For Users

1. Go to your bot's edit page
2. Navigate to the "Tools" tab
3. Find the "Follow-Up Automation" tool
4. Click "Connect" 
5. Configure follow-up settings
6. Choose "Gmail" as the follow-up method
7. Click "Connect" next to Gmail
8. Authorize your Gmail account in the popup
9. Configure the number of follow-ups and other settings
10. Save the configuration

### API Endpoints

The following API endpoints are available:

- `GET /gmail/{bot_id}/config` - Get Gmail configuration
- `GET /gmail/{bot_id}/auth-url` - Get OAuth authorization URL
- `POST /gmail/{bot_id}/connect` - Connect Gmail account
- `POST /gmail/{bot_id}/disconnect` - Disconnect Gmail account
- `GET /gmail/{bot_id}/status` - Get connection status

## Security Considerations

1. **Token Storage**: OAuth tokens are stored encrypted in the database
2. **Scopes**: Only necessary Gmail scopes are requested (`gmail.modify`)
3. **Token Refresh**: Access tokens are automatically refreshed when needed
4. **Revocation**: Tokens are properly revoked when disconnecting

## Troubleshooting

### Common Issues

1. **"redirect_uri_mismatch" error**:
   - Check that your redirect URI in Google Cloud Console matches exactly
   - Make sure you're using HTTPS in production

2. **"Client ID not found" error**:
   - Verify `GOOGLE_CLIENT_ID` environment variable is set
   - Check that the client ID is correct

3. **"Insufficient permissions" error**:
   - Make sure Gmail API is enabled in Google Cloud Console
   - Verify the OAuth scopes are correct

4. **Database connection issues**:
   - Run the migration script: `python scripts/migrate_gmail_configs.py`
   - Check database permissions

### Testing

To test the integration:

1. Create a test bot
2. Go through the Gmail connection flow
3. Check the database to see if the configuration was saved:
   ```sql
   SELECT * FROM gmail_configs WHERE bot_id = 'your_bot_id';
   ```

## Development

### Local Development

For local development, make sure to:

1. Use `http://localhost:3000/gmail-oauth-callback` as redirect URI
2. Set up local environment variables
3. Use a test Gmail account

### Production Deployment

For production:

1. Use HTTPS redirect URIs
2. Set production environment variables
3. Run database migrations
4. Test the full OAuth flow

## Support

If you encounter issues:

1. Check the backend logs for detailed error messages
2. Verify all environment variables are set
3. Test the Google OAuth setup with Google's OAuth playground
4. Ensure all database migrations have been run

## Security Notes

- Never commit OAuth credentials to version control
- Use environment variables for all sensitive configuration
- Regularly rotate OAuth client secrets
- Monitor OAuth token usage and revoke unused tokens 