from app.core.supabase_client import supabase

def ensure_crm_entry(bot_id, first_name=None, last_name=None, phone_number=None, email=None):
    """
    Ensure a CRM entry exists for the given bot and user (by email or phone).
    If not present, insert a new record with whatever details are available.
    """

    ""
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
        print("ALREADY EXISTS")
        return  # Already exists
    insert_result = supabase.table("bot_crms").insert({
        "bot_id": bot_id,
        "first_name": first_name or "",
        "last_name": last_name or "",
        "phone_number": phone_number or "",
        "email": email or ""
    }).execute()
    print("INSERT RESULT:", insert_result) 