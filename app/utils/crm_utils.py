from app.core.supabase_client import supabase
from datetime import datetime

def ensure_crm_entry(bot_id, first_name=None, last_name=None, phone_number=None, email=None):
    """
    Ensure a CRM entry exists for the given bot and user (by email or phone).
    If not present, insert a new record with whatever details are available.
    If present, update the record with any new information provided.
    """

    print("WE ARE TRYING TO MAKE AN ENTRY")
    print("bot_id------>", bot_id)
    print("first_name------>", first_name)
    print("last_name------>", last_name)
    print("phone_number------>", phone_number)
    print("email------>", email)
    

    filters = []
    if email:
        filters.append(f"email.eq.{email}")
    if phone_number:
        filters.append(f"phone_number.eq.{phone_number}")
    if not filters:
        print("NO IDENTIFIER, SKIPPING")
        return  # No identifier, skip
    or_query = ",".join(filters)
    result = supabase.table("bot_crms").select("id").eq("bot_id", bot_id).or_(or_query).execute()
    if result.data and len(result.data) > 0:
        print("ALREADY EXISTS - UPDATING")
        # Update existing record
        update_data = {}
        if first_name is not None:
            update_data["first_name"] = first_name
        if last_name is not None:
            update_data["last_name"] = last_name
        if phone_number is not None:
            update_data["phone_number"] = phone_number
        if email is not None:
            update_data["email"] = email
        if update_data:
            update_data["updated_at"] = datetime.utcnow().isoformat()
            supabase.table("bot_crms").update(update_data).eq("id", result.data[0]["id"]).execute()
        return  # Updated existing record

    # Insert new record if it doesn't exist
    insert_result = supabase.table("bot_crms").insert({
        "bot_id": bot_id,
        "first_name": first_name or "",
        "last_name": last_name or "",
        "phone_number": phone_number or "",
        "email": email or "",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }).execute()
    print("INSERT RESULT:", insert_result) 