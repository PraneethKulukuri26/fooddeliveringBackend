from pydantic import BaseModel, Field
from typing import Optional


class ItemBase(BaseModel):
    name: str
    description: Optional[str] = None


class ItemCreate(ItemBase):
    pass


class Item(ItemBase):
    # MongoDB ObjectId as hex string
    id: str = Field(..., alias="_id")

    class Config:
        allow_population_by_field_name = True


class UserBase(BaseModel):
    email: str
    name: Optional[str] = None
    # Google's subject id (sub) when logging in via Google
    google_id: Optional[str] = None


class UserCreate(UserBase):
    # additional registration fields can be added here
    pass


class User(UserBase):
    id: str = Field(..., alias="_id")
    # whether the user is allowed to donate (boolean flag stored in DB)
    isDoner: Optional[bool] = False

    class Config:
        allow_population_by_field_name = True


# Donation item models
from datetime import datetime
from pydantic import BaseModel


class PickupLocation(BaseModel):
    # simple shape: latitude and longitude as floats and a human address
    latitude: float
    longitude: float
    address: Optional[str] = None


class DonationItemBase(BaseModel):
    title: str
    description: Optional[str] = None
    food_preparation_time: Optional[str] = None
    expire_time: Optional[str] = None
    # path on server where image is saved (optional)
    image: Optional[str] = None
    pickup_location: Optional[PickupLocation] = None
    pick_time: Optional[str] = None


class DonationItemCreate(DonationItemBase):
    pass


class DonationItem(DonationItemBase):
    id: str = Field(..., alias="_id")
    donor_id: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        allow_population_by_field_name = True
