from fastapi import APIRouter, Request, HTTPException, Depends, UploadFile, File, Form
from fastapi import status
from app.auth import get_current_user
from app.models import DonationItemCreate, DonationItem
from typing import Optional, List
from pathlib import Path
import uuid
import os
from datetime import datetime
from bson import ObjectId
import shutil


router = APIRouter()

# Base uploads directory (two levels up from this file -> project root)
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads" / "donations"
os.makedirs(UPLOADS_DIR, exist_ok=True)
def _save_upload(file: UploadFile) -> str:
	"""Save uploaded file to uploads/donations and return a relative URL path."""
	if not file:
		return None
	suffix = Path(file.filename).suffix
	fname = f"{uuid.uuid4().hex}{suffix}"
	dest = UPLOADS_DIR / fname
	# write file
	with dest.open("wb") as out_file:
		shutil.copyfileobj(file.file, out_file)
	# return path relative to server root
	return f"/uploads/donations/{fname}"


def _doc_to_response(doc: dict) -> dict:
	if not doc:
		return None
	if isinstance(doc.get("_id"), ObjectId):
		doc["_id"] = str(doc["_id"])
	if isinstance(doc.get("donor_id"), ObjectId):
		doc["donor_id"] = str(doc["donor_id"])
	return doc


@router.post("/donations", status_code=201, response_model=DonationItem)
async def create_donation(request: Request, current_user: dict = Depends(get_current_user)):
	"""Create a donation item. Only users with isDoner=True can create.

	This handler reads form data at runtime so importing the app doesn't require
	the optional `python-multipart` package to be installed.
	"""
	# authorization check
	if not current_user.get("isDoner"):
		raise HTTPException(status_code=403, detail="User is not authorized to donate")

	db = request.app.state.db

	# read form (works for both application/json or multipart/form-data at runtime)
	form = {}
	try:
		form = await request.form()
	except Exception:
		# not a form (maybe JSON)
		try:
			data = await request.json()
			form = data
		except Exception:
			form = {}

	title = form.get("title")
	if not title:
		raise HTTPException(status_code=400, detail="title is required")

	description = form.get("description")
	food_preparation_time = form.get("food_preparation_time")
	expire_time = form.get("expire_time")
	pick_time = form.get("pick_time")
	latitude = form.get("latitude")
	longitude = form.get("longitude")
	address = form.get("address")

	# handle uploaded file if present
	image_path = None
	uploaded = form.get("image")
	# uploaded may be an UploadFile when multipart is used
	if uploaded is not None and hasattr(uploaded, "filename"):
		image_path = _save_upload(uploaded)

	# convert lat/long to floats if provided as strings
	try:
		if latitude is not None:
			latitude = float(latitude)
		if longitude is not None:
			longitude = float(longitude)
	except Exception:
		raise HTTPException(status_code=400, detail="Invalid latitude/longitude")

	doc = {
		"title": title,
		"description": description,
		"food_preparation_time": food_preparation_time,
		"expire_time": expire_time,
		"image": image_path,
		"pickup_location": {
			"latitude": latitude,
			"longitude": longitude,
			"address": address,
		},
		"pick_time": pick_time,
		"donor_id": ObjectId(current_user["_id"]),
		"created_at": datetime.utcnow(),
	}

	result = await db.donations.insert_one(doc)
	doc["_id"] = str(result.inserted_id)
	# convert donor_id to string for response
	doc["donor_id"] = str(doc["donor_id"])
	return DonationItem.parse_obj(doc)


@router.get("/donations", response_model=List[DonationItem])
async def list_donations(request: Request):
	db = request.app.state.db
	docs = await db.donations.find().to_list(length=200)
	out = []
	for d in docs:
		if isinstance(d.get("_id"), ObjectId):
			d["_id"] = str(d["_id"])
		if isinstance(d.get("donor_id"), ObjectId):
			d["donor_id"] = str(d["donor_id"])
		out.append(d)
	return out


@router.get("/donations/{donation_id}", response_model=DonationItem)
async def get_donation(request: Request, donation_id: str):
	db = request.app.state.db
	try:
		oid = ObjectId(donation_id)
	except Exception:
		raise HTTPException(status_code=404, detail="Not found")
	doc = await db.donations.find_one({"_id": oid})
	if not doc:
		raise HTTPException(status_code=404, detail="Not found")
	if isinstance(doc.get("_id"), ObjectId):
		doc["_id"] = str(doc["_id"])
	if isinstance(doc.get("donor_id"), ObjectId):
		doc["donor_id"] = str(doc["donor_id"])
	return DonationItem.parse_obj(doc)


