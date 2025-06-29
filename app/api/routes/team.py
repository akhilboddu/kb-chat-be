from fastapi import APIRouter, HTTPException, Request
from typing import List
import logging
import uuid

from app.core.supabase_client import supabase
from app.services.auth_service import get_user_from_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/team", tags=["team"])

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def convert_user_id_to_uuid(user_id: str) -> str:
    """Convert Google numeric user IDs to deterministic UUIDs so they match DB."""
    if str(user_id).isdigit():
        namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
        return str(uuid.uuid5(namespace, f"google_user_{user_id}"))
    return user_id

# -----------------------------------------------------------------------------
# Pydantic response models (simple dicts for now to avoid new model files)
# -----------------------------------------------------------------------------

# Returned for each bot the member has access to
BotSummary = dict  # { id: str, name: str }

# Returned for each team member record
TeamMember = dict  # { id, email, member_id, status, role, created_at, updated_at, bots: List[BotSummary] }

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@router.get("/member-count", response_model=dict)
async def get_member_count(request: Request):
    """Return the number of non-owner team members for the authenticated user."""
    auth_token = request.cookies.get("auth_token")
    if not auth_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        user = get_user_from_token(auth_token)
    except Exception as ex:
        logger.warning(f"Invalid auth token while fetching member count: {ex}")
        raise HTTPException(status_code=401, detail="Invalid token") from ex

    owner_uuid = convert_user_id_to_uuid(user["id"])

    try:
        result = (
            supabase.table("team_members")
            .select("id", count="exact", head=True)
            .eq("owner_id", owner_uuid)
            .execute()
        )
    except Exception as ex:
        logger.error(f"Database error fetching member count: {ex}")
        raise HTTPException(status_code=500, detail="Database error") from ex

    count = result.count if hasattr(result, "count") and result.count else 0
    return {"member_count": count}


@router.get("/members", response_model=List[TeamMember])
async def list_team_members(request: Request):
    """Return all team members for the authenticated owner, including their bot access."""
    auth_token = request.cookies.get("auth_token")
    if not auth_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        user = get_user_from_token(auth_token)
    except Exception as ex:
        raise HTTPException(status_code=401, detail="Invalid token") from ex

    owner_uuid = convert_user_id_to_uuid(user["id"])

    try:
        members_result = (
            supabase.table("team_members")
            .select("*")
            .eq("owner_id", owner_uuid)
            .execute()
        )
    except Exception as ex:
        logger.error(f"DB error fetching members: {ex}")
        raise HTTPException(status_code=500, detail="Database error") from ex

    members: List[TeamMember] = []
    data_rows = members_result.data or []
    for row in data_rows:
        member_id = row["id"]
        # Get bot permissions for this member
        try:
            perms_result = (
                supabase.table("bot_permissions")
                .select("bot_id")
                .eq("team_member_id", member_id)
                .execute()
            )
            bot_ids = [b["bot_id"] for b in perms_result.data] if perms_result.data else []
        except Exception:
            bot_ids = []

        bots: List[BotSummary] = []
        if bot_ids:
            try:
                bots_result = (
                    supabase.table("bots")
                    .select("id, name")
                    .in_("id", bot_ids)
                    .execute()
                )
                bots = bots_result.data or []
            except Exception:
                bots = []

        row["bots"] = bots
        # Mark owner flag if the email matches owner
        row["isOwner"] = row.get("email") == user.get("email")
        members.append(row)

    return members


@router.delete("/members/{member_id}", response_model=dict)
async def remove_member(member_id: str, request: Request):
    """Delete a team member and their bot permissions."""
    auth_token = request.cookies.get("auth_token")
    if not auth_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        user = get_user_from_token(auth_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    owner_uuid = convert_user_id_to_uuid(user["id"])

    # Verify the member belongs to this owner
    member_check = (
        supabase.table("team_members")
        .select("id")
        .eq("id", member_id)
        .eq("owner_id", owner_uuid)
        .maybe_single()
        .execute()
    )

    if not member_check.data:
        raise HTTPException(status_code=404, detail="Member not found")

    # Delete permissions first
    supabase.table("bot_permissions").delete().eq("team_member_id", member_id).execute()
    # Delete member
    supabase.table("team_members").delete().eq("id", member_id).execute()

    return {"status": "success", "message": "Member removed"}


@router.put("/members/{member_id}/bots", response_model=dict)
async def update_member_bots(member_id: str, payload: List[str], request: Request):
    """Replace the bot permissions for a team member with the provided list of bot IDs."""
    auth_token = request.cookies.get("auth_token")
    if not auth_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        user = get_user_from_token(auth_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    owner_uuid = convert_user_id_to_uuid(user["id"])

    # Ensure member belongs to owner
    member_check = (
        supabase.table("team_members")
        .select("id")
        .eq("id", member_id)
        .eq("owner_id", owner_uuid)
        .maybe_single()
        .execute()
    )

    if not member_check.data:
        raise HTTPException(status_code=404, detail="Member not found")

    # Delete existing permissions
    supabase.table("bot_permissions").delete().eq("team_member_id", member_id).execute()

    # Insert new permissions
    if payload:
        insert_rows = [{"team_member_id": member_id, "bot_id": bid} for bid in payload]
        supabase.table("bot_permissions").insert(insert_rows).execute()

    return {"status": "success", "message": "Permissions updated"} 