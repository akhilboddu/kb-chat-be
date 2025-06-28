from fastapi import APIRouter, HTTPException, Request
from app.core.supabase_client import supabase
from app.models.profile import UserProfileResponse, UserProfileUpdate, ChangePasswordRequest, UserMetadata
from app.services.auth_service import get_user_from_token
from typing import Dict, Any
import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/profile", tags=["profile"])


def convert_user_id_to_uuid(user_id: str) -> str:
    """Convert Google OAuth user ID to deterministic UUID for database compatibility"""
    if user_id.isdigit():  # Google user ID (numeric string)
        # Create a deterministic UUID from the Google user ID
        namespace = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')  # DNS namespace
        user_uuid = str(uuid.uuid5(namespace, f"google_user_{user_id}"))
        logger.debug(f"Converting Google user ID {user_id} to UUID: {user_uuid}")
        return user_uuid
    else:
        return user_id  # Already a UUID



@router.get("", response_model=UserProfileResponse)
async def get_user_profile(request: Request):
    """Get current user's profile information from Supabase Auth"""
    try:
        logger.info("Getting user profile - checking cookies")
        
        # Get auth token from cookie
        auth_token = request.cookies.get("auth_token")
        logger.info(f"Auth token present: {bool(auth_token)}")
        
        if not auth_token:
            logger.warning("No auth token found in cookies")
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Token received; avoid logging raw token content in production
        logger.info("Auth token received for profile request")
        
        # Validate token and get user info
        try:
            current_user = get_user_from_token(auth_token)
            logger.info(f"Successfully validated token for user: {current_user['email']}")
        except Exception as token_error:
            logger.error(f"Token validation failed: {str(token_error)}")
            logger.error(f"Token validation error type: {type(token_error).__name__}")
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user_id = current_user["id"]
        user_uuid = convert_user_id_to_uuid(user_id)
        logger.info(f"Fetching profile for user: {user_id} (UUID: {user_uuid})")
        logger.info(f"Current user data: {current_user}")
        
        # Get user data from Supabase Auth using admin API (this is the proper way)
        logger.info(f"Calling supabase.auth.admin.get_user_by_id({user_uuid})")
        
        try:
            user_response = supabase.auth.admin.get_user_by_id(user_uuid)
            logger.info(f"Supabase response type: {type(user_response)}")
            
            if not user_response.user:
                logger.error(f"No user found in Supabase for ID: {user_id} (UUID: {user_uuid})")
                raise HTTPException(status_code=404, detail="User not found")
            
            user = user_response.user
            logger.info(f"Found user: {user.email}")
            user_metadata = user.user_metadata or {}
            logger.info(f"User metadata: {user_metadata}")
            
        except HTTPException as http_error:
            logger.error(f"HTTP exception in get_user_profile: {http_error}")
            raise  # Re-raise HTTP exceptions
        except Exception as supabase_error:
            logger.error(f"Supabase admin API error: {supabase_error}")
            logger.error(f"Error type: {type(supabase_error)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            
            # If admin API fails, fall back to user_profiles table for Google OAuth users
            logger.warning("Falling back to user_profiles table due to admin API error (likely Google OAuth user)")
            user_email = current_user["email"]
            user_metadata = {"payment_status": "TRIAL"}
            
            # Try to get profile data from user_profiles table
            try:
                profile_response = supabase.table("user_profiles").select("*").eq("id", user_uuid).execute()
                if profile_response.data:
                    profile_data = profile_response.data[0]
                    user_metadata = {
                        "display_name": profile_data.get("display_name"),
                        "bio": profile_data.get("bio"), 
                        "avatar_url": profile_data.get("avatar_url"),
                        "payment_status": profile_data.get("payment_status", "TRIAL")
                    }
                    logger.info(f"Found profile in user_profiles table: {user_metadata}")
                else:
                    # Create default profile for Google OAuth user
                    logger.info(f"Creating default profile for Google OAuth user: {user_uuid}")
                    current_time = datetime.utcnow()
                    default_profile = {
                        "id": user_uuid,
                        "email": user_email,
                        "display_name": None,
                        "bio": None,
                        "avatar_url": None,
                        "payment_status": "TRIAL",
                        "created_at": current_time.isoformat(),
                        "updated_at": current_time.isoformat()
                    }
                    insert_result = supabase.table("user_profiles").insert(default_profile).execute()
                    logger.info(f"Default profile creation result: {insert_result}")
                    user_metadata = {
                        "display_name": None,
                        "bio": None,
                        "avatar_url": None,
                        "payment_status": "TRIAL"
                    }
            except Exception as table_error:
                logger.error(f"Error with user_profiles table: {table_error}")
                # Try to get payment status from users_metadata table as final fallback
                try:
                    metadata_response = supabase.table("users_metadata").select("payment_status").eq("id", user_uuid).execute()
                    if metadata_response.data:
                        user_metadata["payment_status"] = metadata_response.data[0].get("payment_status", "TRIAL")
                except Exception:
                    pass
        
        # Get live bot count
        try:
            bots_response = supabase.table("bots").select("id").eq("user_id", user_uuid).eq("is_live", True).execute()
            live_bot_count = len(bots_response.data) if bots_response.data else 0
            logger.info(f"Live bot count: {live_bot_count}")
        except Exception as bot_error:
            logger.warning(f"Error fetching bot count: {bot_error}, defaulting to 0")
            live_bot_count = 0
        
        # Parse metadata with defaults (works with both admin API and fallback)
        display_name = user_metadata.get("display_name") or user_metadata.get("full_name") or user_metadata.get("name")
        bio = user_metadata.get("bio")
        avatar_url = user_metadata.get("avatar_url") or user_metadata.get("picture")
        payment_status = user_metadata.get("payment_status", "TRIAL").upper()
        
        # Normalize payment status
        if payment_status in ["PAID", "PRO"]:
            payment_status = "PRO"
        elif payment_status not in ["STARTER", "ENTERPRISE"]:
            payment_status = "TRIAL"
        
        # Use email from admin API if available, otherwise from token
        user_email = getattr(user, 'email', None) if 'user' in locals() else current_user["email"]
        
        logger.info(f"Returning profile for {user_email} with payment status: {payment_status}")
        
        # Return profile response
        from datetime import datetime
        current_time = datetime.utcnow()
        
        try:
            profile_response = UserProfileResponse(
                id=user_id,
                display_name=display_name,
                bio=bio,
                avatar_url=avatar_url,
                email=user_email,
                created_at=getattr(user, 'created_at', current_time) if 'user' in locals() else current_time,
                updated_at=getattr(user, 'updated_at', current_time) if 'user' in locals() else current_time,
                payment_status=payment_status,
                live_bot_count=live_bot_count
            )
            logger.info(f"Successfully created UserProfileResponse: {profile_response}")
            return profile_response
        except Exception as response_error:
            logger.error(f"Error creating UserProfileResponse: {response_error}")
            logger.error(f"Profile data: id={user_id}, email={user_email}, display_name={display_name}")
            raise HTTPException(status_code=500, detail=f"Failed to create profile response: {str(response_error)}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user profile: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch user profile: {str(e)}")


@router.put("", response_model=UserProfileResponse)
async def update_user_profile(
    profile_update: UserProfileUpdate,
    request: Request
):
    """Update current user's profile information in Supabase Auth user_metadata"""
    try:
        logger.info(f"Profile update request received: {profile_update}")
        logger.info(f"Profile update dict: {profile_update.dict()}")
        # Get auth token from cookie
        auth_token = request.cookies.get("auth_token")
        if not auth_token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Validate token and get user info
        try:
            current_user = get_user_from_token(auth_token)
        except Exception as token_error:
            logger.error(f"Token validation failed: {str(token_error)}")
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user_id = current_user["id"]
        user_uuid = convert_user_id_to_uuid(user_id)
        logger.info(f"Updating profile for user: {user_id} (UUID: {user_uuid})")
        
        # Get current user metadata from Supabase Auth admin API
        try:
            user_response = supabase.auth.admin.get_user_by_id(user_uuid)
            if not user_response.user:
                raise HTTPException(status_code=404, detail="User not found")
            
            current_metadata = user_response.user.user_metadata or {}
            logger.info(f"Current metadata: {current_metadata}")
            
            # Prepare updated metadata - only update fields that are provided
            updated_metadata = current_metadata.copy()
            
            if profile_update.display_name is not None:
                updated_metadata["display_name"] = profile_update.display_name
            if profile_update.bio is not None:
                updated_metadata["bio"] = profile_update.bio
            if profile_update.avatar_url is not None:
                updated_metadata["avatar_url"] = profile_update.avatar_url
            
            logger.info(f"Updated metadata: {updated_metadata}")
            
            # Update user metadata in Supabase Auth
            update_response = supabase.auth.admin.update_user_by_id(
                user_uuid,
                {
                    "user_metadata": updated_metadata
                }
            )
            
            if not update_response.user:
                raise HTTPException(status_code=500, detail="Failed to update profile")
                
        except Exception as admin_error:
            logger.error(f"Admin API update failed: {admin_error}")
            # If admin API fails, fall back to user_profiles table for Google OAuth users
            logger.info("Falling back to user_profiles table for profile update")
            
            try:
                # Check if profile exists in user_profiles table
                profile_response = supabase.table("user_profiles").select("*").eq("id", user_uuid).execute()
                
                if profile_response.data:
                    # Update existing profile
                    current_time = datetime.utcnow()
                    update_data = {"updated_at": current_time.isoformat()}
                    if profile_update.display_name is not None:
                        update_data["display_name"] = profile_update.display_name
                    if profile_update.bio is not None:
                        update_data["bio"] = profile_update.bio
                    if profile_update.avatar_url is not None:
                        update_data["avatar_url"] = profile_update.avatar_url
                    
                    logger.info(f"Updating user_profiles with data: {update_data}")
                    result = supabase.table("user_profiles").update(update_data).eq("id", user_uuid).execute()
                    logger.info(f"Update result: {result}")
                    logger.info(f"Updated profile in user_profiles table for user: {user_uuid}")
                else:
                    # Create new profile
                    current_time = datetime.utcnow()
                    new_profile = {
                        "id": user_uuid,
                        "email": current_user["email"],
                        "display_name": profile_update.display_name,
                        "bio": profile_update.bio,
                        "avatar_url": profile_update.avatar_url,
                        "payment_status": "TRIAL",
                        "created_at": current_time.isoformat(),
                        "updated_at": current_time.isoformat()
                    }
                    logger.info(f"Creating new profile with data: {new_profile}")
                    result = supabase.table("user_profiles").insert(new_profile).execute()
                    logger.info(f"Insert result: {result}")
                    logger.info(f"Created new profile in user_profiles table for user: {user_uuid}")
                    
            except Exception as table_error:
                logger.error(f"Failed to update profile in user_profiles table: {table_error}")
                raise HTTPException(status_code=500, detail="Profile update failed")
        
        logger.info(f"Successfully updated profile for user: {user_id}")
        
        # Return updated profile by calling get_user_profile
        logger.info("Calling get_user_profile to return updated data")
        return await get_user_profile(request)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user profile: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to update user profile")



@router.post("/change-password")
async def change_password(
    password_request: ChangePasswordRequest,
    request: Request
):
    """Change user's password using Supabase Auth Admin API"""
    try:
        # Get auth token from cookie
        auth_token = request.cookies.get("auth_token")
        if not auth_token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Validate token and get user info
        try:
            current_user = get_user_from_token(auth_token)
        except Exception as token_error:
            logger.error(f"Token validation failed: {str(token_error)}")
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user_id = current_user["id"]
        user_uuid = convert_user_id_to_uuid(user_id)
        logger.info(f"Password change request for user: {user_id} (UUID: {user_uuid})")
        
        # Validate passwords match
        if password_request.new_password != password_request.confirm_password:
            raise HTTPException(status_code=400, detail="Passwords do not match")
        
        # Validate password length
        if len(password_request.new_password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        
        # Update password using Supabase Auth Admin API
        try:
            result = supabase.auth.admin.update_user_by_id(
                user_uuid,
                {
                    "password": password_request.new_password
                }
            )
            
            if not result.user:
                raise HTTPException(status_code=500, detail="Failed to update password")
                
        except Exception as admin_error:
            logger.error(f"Admin API password update failed: {admin_error}")
            raise HTTPException(status_code=500, detail="Failed to update password")
        
        logger.info(f"Successfully updated password for user: {user_id}")
        return {"message": "Password updated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error changing password: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Failed to change password")