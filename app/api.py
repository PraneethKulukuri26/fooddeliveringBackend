from fastapi import APIRouter, HTTPException
from typing import List
from app.models import Item, ItemCreate

router = APIRouter()

# simple in-memory store for demo
_items = {}
_next_id = 1

@router.get("/items", response_model=List[Item])
def list_items():
    return list(_items.values())

@router.post("/items", response_model=Item, status_code=201)
def create_item(payload: ItemCreate):
    global _next_id
    item = Item(id=_next_id, **payload.dict())
    _items[_next_id] = item
    _next_id += 1
    return item

@router.get("/items/{item_id}", response_model=Item)
def get_item(item_id: int):
    item = _items.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    return item
