from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi import Depends
import requests

security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        SUPABASE_URL = "https://qbhevelbszcvxkutfmlg.supabase.co"
        token = credentials.credentials

        anon_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFiaGV2ZWxic3pjdnhrdXRmbWxnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDMzNTUyMDEsImV4cCI6MjA1ODkzMTIwMX0.LNI1h9fuJyrvHmb5GrSFesMil7kYPaB7AG7LH5WHgDA"
        res = requests.get(
            url=f"{SUPABASE_URL}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": anon_key},
        )
        res_json = res.json()
        if res_json["id"]:
            return res_json
        return None
    except Exception as e:
        print(e)
