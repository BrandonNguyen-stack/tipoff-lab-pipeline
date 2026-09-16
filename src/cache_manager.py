import json
import os
from datetime import datetime, timezone
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

def get_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def save_cache(key, data):
    try:
        sb = get_supabase()
        sb.table("cache").upsert({
            "key": key,
            "data": data,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).execute()
        print(f"Cached {key}.")
    except Exception as e:
        print(f"Cache save failed for {key}: {e}")

def load_cache(key, max_age_hours=23):
    try:
        sb = get_supabase()
        result = sb.table("cache").select("data,updated_at").eq("key", key).execute()
        if not result.data:
            return None
        row = result.data[0]
        updated_at = datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00"))
        age_hours = (datetime.now(timezone.utc) - updated_at).total_seconds() / 3600
        if age_hours > max_age_hours:
            print(f"Cache {key} is {age_hours:.1f}h old, needs refresh.")
            return None
        print(f"Using cached {key} ({age_hours:.1f}h old).")
        return row["data"]
    except Exception as e:
        print(f"Cache load failed for {key}: {e}")
        return None
