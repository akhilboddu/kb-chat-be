import os
from fastapi import APIRouter, HTTPException, Response, Request, Query
from fastapi.responses import RedirectResponse
from app.core.supabase_client import supabase
from app.models.auth import (
    UserLoginRequest, UserRegisterRequest, AuthResponse,
    PasswordResetRequest, PasswordResetConfirm, GoogleAuthResponse,
    EmailConfirmationRequest, RefreshTokenRequest, UserInfo
)
from app.services.auth_service import (
    create_secure_session, validate_session, invalidate_session,
    refresh_session, get_user_from_token
)
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Get URLs from environment
FRONTEND_URL = os.getenv("VITE_BASE_URL", "http://localhost:8080")  # Use VITE_BASE_URL for frontend
BACKEND_URL = os.getenv("BASE_URL", "http://localhost:8000")  # Use BASE_URL for backend

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/register", response_model=dict)
async def register(user_data: UserRegisterRequest):
    """Handle user registration with email confirmation"""
    try:
        logger.info(f"Registration attempt for email: {user_data.email}")
        
        # Test basic Supabase connection and sign up - correct syntax for Python client
        try:
            result = supabase.auth.sign_up({
                "email": user_data.email,
                "password": user_data.password,
                "options": {
                    "email_redirect_to": f"{FRONTEND_URL}/auth?type=email_confirmation"
                }
            })
            logger.info(f"Supabase signup result type: {type(result)}")
            logger.info(f"Supabase signup result: {result}")
        except Exception as supabase_error:
            error_message = str(supabase_error)
            logger.error(f"Supabase signup error: {error_message}")
            
            # Handle timeout errors gracefully - email might still have been sent
            if "timed out" in error_message.lower() or "timeout" in error_message.lower():
                logger.warning(f"Supabase signup timed out for {user_data.email}, but email may have been sent")
                return {
                    "message": "Registration request submitted! Please check your email for confirmation. If you don't receive an email within a few minutes, please try again.",
                    "requires_email_confirmation": True
                }
            else:
                raise HTTPException(status_code=500, detail=f"Registration failed: {error_message}")
        
        # Check if there was an error in the result
        if hasattr(result, 'error') and result.error:
            logger.error(f"Registration error: {result.error.message}")
            raise HTTPException(status_code=400, detail=result.error.message)
        
        # Check if user already exists (identities will be empty)
        if hasattr(result, 'user') and result.user and hasattr(result.user, 'identities') and len(result.user.identities) == 0:
            raise HTTPException(status_code=400, detail="Email already exists")
        
        # Check if we have a session (immediate confirmation) or needs email confirmation
        requires_confirmation = not hasattr(result, 'session') or result.session is None
        
        logger.info(f"Registration successful for {user_data.email}, requires confirmation: {requires_confirmation}")
        
        return {
            "message": "Registration successful! Please check your email for confirmation.",
            "requires_email_confirmation": requires_confirmation
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration exception: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")


@router.post("/resend-verification", response_model=dict)
async def resend_verification_email(request_data: dict):
    """Resend verification email for unverified users"""
    try:
        email = request_data.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")
        
        logger.info(f"Resending verification email for: {email}")
        
        # Use Supabase's resend method
        result = supabase.auth.resend({
            "type": "signup",
            "email": email,
            "options": {
                "email_redirect_to": f"{FRONTEND_URL}/auth?type=email_confirmation"
            }
        })
        
        if hasattr(result, 'error') and result.error:
            logger.error(f"Resend verification error: {result.error.message}")
            # Don't expose exact error details for security
            return {
                "message": "If this email is registered and unverified, a new verification email has been sent.",
                "success": True
            }
        
        logger.info(f"Verification email resent successfully for: {email}")
        return {
            "message": "Verification email sent! Please check your inbox.",
            "success": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Resend verification exception: {str(e)}")
        # Return success message anyway for security (don't leak user existence)
        return {
            "message": "If this email is registered and unverified, a new verification email has been sent.",
            "success": True
        }


@router.post("/login", response_model=AuthResponse)
async def login(user_data: UserLoginRequest, response: Response):
    """Handle user login with secure session creation"""
    try:
        logger.info(f"Login attempt for email: {user_data.email}")
        
        # Test basic Supabase connection first
        try:
            # Sign in with Supabase - correct syntax for Python client
            result = supabase.auth.sign_in_with_password({
                "email": user_data.email,
                "password": user_data.password
            })
            logger.info(f"Supabase auth result type: {type(result)}")
            logger.info(f"Supabase auth result attributes: {dir(result)}")
            logger.info(f"Supabase auth result: {result}")
        except Exception as supabase_error:
            logger.error(f"Supabase auth error: {str(supabase_error)}")
            raise HTTPException(status_code=500, detail=f"Supabase auth error: {str(supabase_error)}")
        
        # Check if the result has user and session (success case)
        if not result.user or not result.session:
            logger.error(f"Login failed - no user or session in result")
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        # Create secure session token
        user_dict = {
            "id": result.user.id,
            "email": result.user.email
        }
        
        try:
            secure_token = create_secure_session(user_dict)
            logger.info(f"Successfully created secure token for user {user_dict['id']}")
        except Exception as token_error:
            logger.error(f"Token creation error: {str(token_error)}")
            raise HTTPException(status_code=500, detail="Failed to create secure session")
        
        # Set httpOnly cookie
        response.set_cookie(
            key="auth_token",
            value=secure_token,
            httponly=True,
            secure=False,  # Set to False for localhost development
            samesite="lax",
            max_age=86400,  # 24 hours
            path="/",  # Ensure cookie is available for all paths
            domain=None  # Don't set domain for localhost
        )
        
        return AuthResponse(
            access_token=secure_token,
            refresh_token=result.session.refresh_token,
            user_id=result.user.id,
            email=result.user.email,
            expires_in=86400  # 24 hours
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login exception: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")


@router.get("/email-confirmation")
async def confirm_email(
    request: Request,
    access_token: Optional[str] = Query(None, alias="access_token"),
    refresh_token: Optional[str] = Query(None, alias="refresh_token"),
    type: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_code: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None)
):
    """Handle email confirmation callback from Supabase"""
    try:
        logger.info(f"Email confirmation callback received")
        logger.info(f"  - access_token: {access_token[:20] + '...' if access_token else 'None'}")
        logger.info(f"  - refresh_token: {refresh_token[:20] + '...' if refresh_token else 'None'}")
        logger.info(f"  - error: {error}")
        logger.info(f"  - error_code: {error_code}")
        logger.info(f"  - error_description: {error_description}")
        logger.info(f"  - full URL: {str(request.url)}")
        
        # Handle error cases first
        if error or error_code:
            logger.error(f"Email confirmation error: {error} - {error_code} - {error_description}")
            
            # Handle specific error types
            if error_code == "otp_expired":
                return RedirectResponse(
                    url=f"{FRONTEND_URL}/auth?error=link_expired&message=Email confirmation link has expired. Please request a new one.",
                    status_code=302
                )
            elif error == "access_denied":
                return RedirectResponse(
                    url=f"{FRONTEND_URL}/auth?error=access_denied&message=Email confirmation was denied or cancelled.",
                    status_code=302
                )
            else:
                return RedirectResponse(
                    url=f"{FRONTEND_URL}/auth?error=confirmation_failed&message={error_description or 'Email confirmation failed'}",
                    status_code=302
                )
        
        # Handle missing tokens
        if not access_token or not refresh_token:
            logger.error("Email confirmation missing required tokens")
            return RedirectResponse(
                url=f"{FRONTEND_URL}/auth?error=missing_tokens&message=Email confirmation link is missing required information.",
                status_code=302
            )
        
        # Set session with Supabase
        result = supabase.auth.set_session({
            "access_token": access_token,
            "refresh_token": refresh_token
        })
        
        if result.error:
            logger.error(f"Email confirmation session error: {result.error.message}")
            return RedirectResponse(
                url=f"{FRONTEND_URL}/auth?error=confirmation_failed&message={result.error.message}",
                status_code=302
            )
        
        # Create secure session
        user_dict = {
            "id": result.user.id,
            "email": result.user.email
        }
        secure_token = create_secure_session(user_dict)
        
        logger.info(f"Email confirmation successful for user: {result.user.email}")
        
        # Redirect to frontend with secure token
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth?token={secure_token}&confirmed=true",
            status_code=302
        )
        
    except Exception as e:
        logger.error(f"Email confirmation exception: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth?error=confirmation_failed&message=An error occurred during email confirmation",
            status_code=302
        )


@router.post("/google-session", response_model=AuthResponse)
async def create_google_session(request_data: dict, response: Response):
    """Create backend session from Google OAuth tokens"""
    try:
        logger.info("Creating backend session from Google OAuth tokens")
        
        access_token = request_data.get("access_token")
        refresh_token = request_data.get("refresh_token") 
        user_data = request_data.get("user")
        
        if not access_token or not user_data:
            raise HTTPException(status_code=400, detail="Missing OAuth tokens or user data")
        
        logger.info(f"Creating session for Google user: {user_data.get('email')}")
        
        # Create secure session token
        user_dict = {
            "id": user_data.get("id"),
            "email": user_data.get("email")
        }
        
        secure_token = create_secure_session(user_dict)
        
        # Set httpOnly cookie
        response.set_cookie(
            key="auth_token",
            value=secure_token,
            httponly=True,
            secure=False,  # Set to False for localhost development
            samesite="lax",
            max_age=86400,  # 24 hours
            path="/",  # Ensure cookie is available for all paths
            domain=None  # Don't set domain for localhost
        )
        
        logger.info(f"Successfully created backend session for: {user_data.get('email')}")
        
        return AuthResponse(
            access_token=secure_token,
            refresh_token=refresh_token,
            user_id=user_data.get("id"),
            email=user_data.get("email"),
            expires_in=86400  # 24 hours
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Google session creation exception: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to create Google session: {str(e)}")


@router.post("/google", response_model=GoogleAuthResponse)
async def google_oauth_init():
    """Initiate Google OAuth flow"""
    try:
        logger.info("Initiating Google OAuth flow with implicit flow")
        
        # Try to force implicit flow by setting query parameters
        result = supabase.auth.sign_in_with_oauth({
            "provider": "google",
            "options": {
                "redirect_to": f"{FRONTEND_URL}/auth",  # Direct to frontend
                "query_params": {
                    "response_type": "token",  # Force implicit flow
                    "flow_type": "implicit"
                }
            }
        })
        
        logger.info(f"OAuth result: {result}")
        
        # Extract OAuth URL from the result
        oauth_url = result.url
        logger.info(f"Generated OAuth URL: {oauth_url}")
        return GoogleAuthResponse(oauth_url=oauth_url)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Google OAuth init exception: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to initiate Google sign in: {str(e)}")


@router.get("/google/callback")
async def google_oauth_callback(
    request: Request,
    response: Response,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    access_token: Optional[str] = Query(None),
    refresh_token: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None)
):
    """Handle Google OAuth callback"""
    try:
        # CRITICAL DEBUG: Force log this immediately
        print("🔥 OAUTH CALLBACK HIT!")
        print(f"🔥 CODE: {code}")
        print(f"🔥 STATE: {state}")
        print(f"🔥 ERROR: {error}")
        
        # Log all received parameters for debugging
        logger.info(f"🔥 CRITICAL: Google OAuth callback received!")
        logger.info(f"  - code: {code}")
        logger.info(f"  - state: {state}")
        logger.info(f"  - access_token: {access_token}")
        logger.info(f"  - refresh_token: {refresh_token}")
        logger.info(f"  - error: {error}")
        logger.info(f"  - error_description: {error_description}")
        logger.info(f"  - request URL: {str(request.url)}")
        
        # Check for errors from OAuth provider
        if error:
            logger.error(f"OAuth error: {error} - {error_description}")
            return RedirectResponse(
                url=f"{FRONTEND_URL}/auth?error=oauth_failed&message={error_description or error}",
                status_code=302
            )
        
        # If we have tokens directly (Supabase implicit flow)
        if access_token and refresh_token:
            # Set session with tokens
            result = supabase.auth.set_session({
                "access_token": access_token,
                "refresh_token": refresh_token
            })
            
            if result.error:
                logger.error(f"Google OAuth session error: {result.error.message}")
                return RedirectResponse(
                    url=f"{FRONTEND_URL}/auth?error=oauth_failed",
                    status_code=302
                )
            
            # Create secure session
            user_dict = {
                "id": result.user.id,
                "email": result.user.email
            }
            secure_token = create_secure_session(user_dict)
            
            # Set httpOnly cookie (same as login endpoint)
            response.set_cookie(
                key="auth_token",
                value=secure_token,
                httponly=True,
                secure=False,  # Set to False for localhost development
                samesite="lax",
                max_age=86400,  # 24 hours
                path="/",  # Ensure cookie is available for all paths
                domain=None  # Don't set domain for localhost
            )
            
            # Redirect to frontend (cookie is now set for session persistence)
            return RedirectResponse(
                url=f"{FRONTEND_URL}/auth?provider=google&success=true",
                status_code=302
            )
        
        # If we have an authorization code (most common OAuth flow)
        if code:
            logger.info(f"Processing OAuth code on backend to avoid PKCE issues")
            try:
                # Since PKCE is causing issues, let's try a different approach
                # Use the implicit flow tokens if they're in URL fragments, or check if session exists
                
                # Check if Supabase automatically set a session during the OAuth callback
                try:
                    current_session = supabase.auth.get_session()
                    logger.info(f"Current Supabase session: {current_session}")
                    
                    if current_session and current_session.user:
                        logger.info(f"Found existing session for user: {current_session.user.email}")
                        
                        # Create secure session
                        user_dict = {
                            "id": current_session.user.id,
                            "email": current_session.user.email
                        }
                        secure_token = create_secure_session(user_dict)
                        
                        # Set httpOnly cookie
                        response.set_cookie(
                            key="auth_token",
                            value=secure_token,
                            httponly=True,
                            secure=False,
                            samesite="lax",
                            max_age=86400,
                            path="/",
                            domain=None
                        )
                        
                        logger.info(f"Successfully authenticated user: {current_session.user.email}")
                        return RedirectResponse(
                            url=f"{FRONTEND_URL}/auth?provider=google&success=true",
                            status_code=302
                        )
                except Exception as session_error:
                    logger.error(f"Session check failed: {session_error}")
                
                # If no session exists, redirect to frontend with just success message
                # The frontend can try to get the session from the URL hash fragments
                logger.info("No backend session found, redirecting to frontend for implicit flow handling")
                return RedirectResponse(
                    url=f"{FRONTEND_URL}/auth?provider=google&oauth_redirect=true",
                    status_code=302
                )
                
            except Exception as oauth_error:
                logger.error(f"OAuth processing error: {str(oauth_error)}")
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
                return RedirectResponse(
                    url=f"{FRONTEND_URL}/auth?error=oauth_failed&message=oauth_processing_error",
                    status_code=302
                )
        
        # If we get here, no valid parameters were provided
        logger.error("No valid OAuth parameters received (no tokens, no code)")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth?error=oauth_failed&message=no_valid_parameters",
            status_code=302
        )
        
    except Exception as e:
        logger.error(f"Google OAuth callback exception: {str(e)}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth?error=oauth_failed",
            status_code=302
        )


@router.post("/forgot-password", response_model=dict)
async def forgot_password(request_data: PasswordResetRequest):
    """Send password reset email"""
    try:
        result = supabase.auth.reset_password_for_email(
            request_data.email,
            {
                "redirectTo": f"{BACKEND_URL}/api/auth/reset-password-callback"
            }
        )
        
        if result.error:
            logger.error(f"Password reset error: {result.error.message}")
            raise HTTPException(status_code=400, detail=result.error.message)
        
        return {"message": "Password reset email sent! Please check your inbox."}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Password reset exception: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to send password reset email")


@router.get("/reset-password-callback")
async def reset_password_callback(
    access_token: str = Query(..., alias="access_token"),
    refresh_token: str = Query(..., alias="refresh_token"),
    type: str = Query(...)
):
    """Handle password reset callback from Supabase"""
    try:
        # Redirect to frontend with tokens for password reset form
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth?type={type}&access_token={access_token}&refresh_token={refresh_token}",
            status_code=302
        )
    except Exception as e:
        logger.error(f"Password reset callback exception: {str(e)}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth?error=reset_failed",
            status_code=302
        )


@router.post("/reset-password", response_model=dict)
async def reset_password(reset_data: PasswordResetConfirm):
    """Handle password reset confirmation"""
    try:
        # First set the session with the token
        session_result = supabase.auth.set_session({
            "access_token": reset_data.token,
            "refresh_token": ""  # Not needed for password reset
        })
        
        if session_result.error:
            logger.error(f"Password reset session error: {session_result.error.message}")
            raise HTTPException(status_code=400, detail="Invalid or expired reset token")
        
        # Now update the password
        result = supabase.auth.update_user({
            "password": reset_data.new_password
        })
        
        if result.error:
            logger.error(f"Password update error: {result.error.message}")
            raise HTTPException(status_code=400, detail=result.error.message)
        
        return {"message": "Password updated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Password reset exception: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to reset password")


@router.post("/logout", response_model=dict)
async def logout(request: Request, response: Response):
    """Handle user logout"""
    try:
        # Get auth token from cookie
        auth_token = request.cookies.get("auth_token")
        
        if auth_token:
            # Validate and get user info
            try:
                user_info = get_user_from_token(auth_token)
                # Invalidate session in our system
                invalidate_session(user_info["id"])
            except:
                pass  # Token might be invalid, continue with logout
        
        # Sign out from Supabase
        supabase.auth.sign_out()
        
        # Clear cookies
        response.delete_cookie("auth_token")
        response.delete_cookie("refresh_token")
        
        return {"message": "Logged out successfully"}
        
    except Exception as e:
        logger.error(f"Logout exception: {str(e)}")
        # Still clear cookies even if there's an error
        response.delete_cookie("auth_token")
        response.delete_cookie("refresh_token")
        return {"message": "Logged out"}


@router.post("/refresh", response_model=AuthResponse)
async def refresh_token(request: Request, response: Response):
    """Refresh user session"""
    try:
        # Get refresh token from cookie
        refresh_token = request.cookies.get("refresh_token")
        
        if not refresh_token:
            raise HTTPException(status_code=401, detail="No refresh token provided")
        
        # Refresh session with Supabase
        result = supabase.auth.refresh_session(refresh_token)
        
        if result.error:
            logger.error(f"Session refresh error: {result.error.message}")
            raise HTTPException(status_code=401, detail="Failed to refresh session")
        
        # Create new secure session
        user_dict = {
            "id": result.user.id,
            "email": result.user.email
        }
        new_secure_token = refresh_session(refresh_token, user_dict)
        
        # Update cookies
        response.set_cookie(
            key="auth_token",
            value=new_secure_token,
            httponly=True,
            secure=os.getenv("ENVIRONMENT") == "production",
            samesite="lax",
            max_age=86400  # 24 hours
        )
        
        response.set_cookie(
            key="refresh_token",
            value=result.session.refresh_token,
            httponly=True,
            secure=os.getenv("ENVIRONMENT") == "production",
            samesite="lax",
            max_age=604800  # 7 days
        )
        
        return AuthResponse(
            access_token=new_secure_token,
            refresh_token=result.session.refresh_token,
            user_id=result.user.id,
            email=result.user.email,
            expires_in=86400  # 24 hours
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh exception: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to refresh token")


@router.get("/me", response_model=UserInfo)
async def get_current_user(request: Request):
    """Get current user information"""
    try:
        logger.info("Getting current user - checking cookies")
        
        # Get auth token from cookie
        auth_token = request.cookies.get("auth_token")
        logger.info(f"Auth token present: {bool(auth_token)}")
        
        if not auth_token:
            logger.warning("No auth token found in cookies")
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Log token details (first 20 chars for security)
        logger.info(f"Token starts with: {auth_token[:20]}...")
        
        # Validate token and get user info
        try:
            user_info = get_user_from_token(auth_token)
            logger.info(f"Successfully validated token for user: {user_info['email']}")
        except Exception as token_error:
            logger.error(f"Token validation failed: {str(token_error)}")
            logger.error(f"Token validation error type: {type(token_error).__name__}")
            raise HTTPException(status_code=401, detail="Invalid token")
        
        # For now, just return the user info from the token without additional Supabase call
        # TODO: Add Supabase user lookup if needed for additional user data
        return UserInfo(
            id=user_info["id"],
            email=user_info["email"],
            created_at=None,  # Will be None for now
            email_confirmed_at=None  # Will be None for now
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get current user exception: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to get user information: {str(e)}")