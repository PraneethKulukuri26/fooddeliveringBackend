from fastapi import APIRouter, Request, HTTPException
from fastapi import Depends
from dotenv import load_dotenv
load_dotenv()
from fastapi import status
from typing import Optional, Any, Dict, List
from pydantic import BaseModel, EmailStr
import os
import jwt
from datetime import datetime, timedelta
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import Field
from passlib.context import CryptContext

router = APIRouter()
security = HTTPBearer()

SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# Password hashing context
# Use PBKDF2-SHA256 to avoid dependency on the bcrypt native library and
# to eliminate bcrypt's 72-byte password limit. PBKDF2-SHA256 is supported
# by passlib without extra native dependencies.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


class Location(BaseModel):
    address: str
    pincode: Optional[str] = None
    coordinates: Optional[List[float]] = None


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    password: str
    role: Optional[str] = "donor"
    acceptTerms: Optional[bool] = False
    location: Optional[Location] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


def _create_token(user_id: str, email: str) -> str:
    to_encode = {"sub": user_id, "email": email}
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return token


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(request: Request, payload: RegisterRequest):
    """Register user directly with email/password and return JWT."""
    db = request.app.state.db

    # basic acceptance of terms check
    if payload.acceptTerms is False:
        # allow registration but warn—here we require acceptTerms True for non-consumer roles
        # if role indicates a provider (donor/both) ensure terms accepted
        if payload.role in ("donor", "both"):
            raise HTTPException(status_code=400, detail="acceptTerms must be true for donors")

    # ensure email/phone uniqueness (case-insensitive for email)
    existing_email = await db.users.find_one({"email": {"$regex": f"^{payload.email}$", "$options": "i"}})
    existing_phone = None
    if payload.phone:
        existing_phone = await db.users.find_one({"phone": payload.phone})

    if existing_email and existing_phone:
        # both email and phone already present
        raise HTTPException(status_code=400, detail="Email and phone already registered")
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")
    if existing_phone:
        raise HTTPException(status_code=400, detail="Phone already registered")

    hashed = pwd_context.hash(payload.password)

    doc = {
        "name": payload.name,
        "email": payload.email,
        "phone": payload.phone,
        "hashed_password": hashed,
        "role": payload.role,
        "acceptTerms": payload.acceptTerms,
        "location": payload.location.dict() if payload.location else None,
        # convenience flag for donors
        "isDoner": True if payload.role in ("donor", "both") else False,
        "created_at": datetime.utcnow(),
    }

    try:
        result = await db.users.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="User already exists")

    doc["_id"] = str(result.inserted_id)
    token = _create_token(doc["_id"], payload.email)
    # do not return hashed password
    doc.pop("hashed_password", None)
    return {"status": "created", "user": doc, "access_token": token, "token_type": "bearer"}


@router.post("/login")
async def login(request: Request, payload: LoginRequest):
    db = request.app.state.db
    user = await db.users.find_one({"email": {"$regex": f"^{payload.email}$", "$options": "i"}})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    hashed = user.get("hashed_password")
    if not hashed or not pwd_context.verify(payload.password, hashed):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user["_id"] = str(user["_id"]) if isinstance(user.get("_id"), ObjectId) else user.get("_id")
    token = _create_token(user["_id"], user.get("email"))
    user.pop("hashed_password", None)
    return {"access_token": token, "token_type": "bearer", "user": user}


from fastapi import Body


async def get_current_user(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token: missing sub")
    except Exception:
        raise HTTPException(status_code=401, detail="Could not validate credentials")

    db = request.app.state.db
    try:
        oid = ObjectId(user_id)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid user id in token")

    user = await db.users.find_one({"_id": oid})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    # convert _id to str for response convenience
    user["_id"] = str(user["_id"])
    # do not leak hashed_password
    user.pop("hashed_password", None)
    return user


@router.get("/me")
async def get_me(request: Request, current_user: dict = Depends(get_current_user)):
    return {"user": current_user}


@router.patch("/me")
async def update_me(request: Request, update: Dict[str, Any] = Body(...), current_user: dict = Depends(get_current_user)):
    db = request.app.state.db
    updates: Dict[str, Any] = {}

    # Do not allow changing the primary key
    if "_id" in update:
        del update["_id"]

    # Validate and prepare email if provided
    if "email" in update:
        new_email = update["email"]
        try:
            # validate format
            EmailStr(new_email)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid email format")
        # ensure email uniqueness (case-insensitive) excluding current user
        existing = await db.users.find_one({"email": {"$regex": f"^{new_email}$", "$options": "i"}, "_id": {"$ne": ObjectId(current_user["_id"])}})
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")
        updates["email"] = new_email

    # Copy other provided fields to updates (overwrite/add)
    for k, v in update.items():
        if k == "email":
            continue
        # skip invalid key
        if k == "_id":
            continue
        # if updating password, hash it
        if k == "password":
            updates["hashed_password"] = pwd_context.hash(v)
            continue
        updates[k] = v

    if not updates:
        return {"user": current_user}

    await db.users.update_one({"_id": ObjectId(current_user["_id"])}, {"$set": updates})
    user = await db.users.find_one({"_id": ObjectId(current_user["_id"])})
    user["_id"] = str(user["_id"])
    user.pop("hashed_password", None)
    return {"user": user}
