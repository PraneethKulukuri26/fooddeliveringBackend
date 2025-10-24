from fastapi import APIRouter, Request, HTTPException
from dotenv import load_dotenv
load_dotenv()
from fastapi import status
from typing import Optional
from pydantic import BaseModel, EmailStr
import os
import httpx
from app.models import UserCreate, User
import jwt
from datetime import datetime, timedelta
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
import logging

router = APIRouter()

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
print(CLIENT_ID, CLIENT_SECRET)
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# Log the client id we loaded (safe to log non-secret client identifier) to help debugging
logging.getLogger("uvicorn.error").info("GOOGLE_CLIENT_ID=%s", CLIENT_ID)

@router.get("/login")
def login():
    if not CLIENT_ID:
        raise HTTPException(status_code=500, detail="Google OAuth client ID not configured")
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    # return URL to frontend
    from urllib.parse import urlencode
    url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return {"auth_url": url}


class RegisterRequest(BaseModel):
    # Client may provide either an id_token (JWT) OR an authorization code (server-side exchange)
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    google_id: Optional[str] = None
    id_token: Optional[str] = None
    code: Optional[str] = None
    code_verifier: Optional[str] = None
    redirect_uri: Optional[str] = None


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(request: Request, payload: RegisterRequest):
    db = request.app.state.db

    email = payload.email
    name = payload.name
    google_id = payload.google_id

    # If an authorization code is provided, exchange it for tokens and fetch userinfo
    if payload.code:
        # Determine effective redirect URI (allow override if provided)
        effective_redirect = payload.redirect_uri or REDIRECT_URI

        # Build form data for token exchange
        data = {
            "code": payload.code,
            "client_id": CLIENT_ID,
            "redirect_uri": effective_redirect,
            "grant_type": "authorization_code",
        }
        # include client_secret when available (confidential clients)
        if CLIENT_SECRET:
            data["client_secret"] = CLIENT_SECRET
        # include code_verifier for PKCE flows when provided
        if payload.code_verifier:
            data["code_verifier"] = payload.code_verifier

        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(GOOGLE_TOKEN_URL, data=data, headers=headers)
            if token_resp.status_code != 200:
                # surface Google's error body when possible
                try:
                    err = token_resp.json()
                except Exception:
                    err = {"status": token_resp.status_code, "text": token_resp.text}
                raise HTTPException(status_code=400, detail={"error": "token_exchange_failed", "info": err})
            token_json = token_resp.json()
            id_token = token_json.get("id_token")
            access_token = token_json.get("access_token")

            # Use access_token to fetch userinfo
            user_resp = await client.get(GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access_token}"})
            if user_resp.status_code != 200:
                try:
                    err = user_resp.json()
                except Exception:
                    err = {"status": user_resp.status_code, "text": user_resp.text}
                raise HTTPException(status_code=400, detail={"error": "userinfo_fetch_failed", "info": err})
            userinfo = user_resp.json()

        # Extract mandatory fields
        google_sub = userinfo.get("sub")
        tok_email = userinfo.get("email")
        if not google_sub or not tok_email:
            raise HTTPException(status_code=400, detail="Incomplete userinfo from Google")
        # set google_id and email from userinfo
        google_id = google_sub
        email = email or tok_email

    # If id_token is provided directly, validate it and extract sub/email
    elif payload.id_token:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://oauth2.googleapis.com/tokeninfo?id_token={payload.id_token}")
            if resp.status_code != 200:
                raise HTTPException(status_code=400, detail="Invalid id_token")
            info = resp.json()
            sub = info.get("sub")
            tok_email = info.get("email")
            if not sub or not tok_email:
                raise HTTPException(status_code=400, detail="Invalid id_token payload")
            google_id = sub
            email = email or tok_email

    # At this point we must have an email to create the user
    if not email:
        raise HTTPException(status_code=400, detail="Email is required for registration")

    # Ensure google_id uniqueness if present
    if google_id:
        found = await db.users.find_one({"google_id": google_id})
        if found:
            raise HTTPException(status_code=400, detail="Google account already linked to another user")

    # Ensure email uniqueness (case-insensitive)
    found_email = await db.users.find_one({"email": {"$regex": f"^{email}$", "$options": "i"}})
    if found_email:
        raise HTTPException(status_code=400, detail="User already exists")

    doc = {"email": email, "name": name}
    if google_id:
        doc["google_id"] = google_id

    try:
        result = await db.users.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="User already exists")

    doc["_id"] = str(result.inserted_id)

    # create JWT token for immediate login
    to_encode = {"sub": doc["_id"], "email": email}
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    return {"status": "created", "user": doc, "access_token": token, "token_type": "bearer"}
