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

    class Config:
        allow_population_by_field_name = True
