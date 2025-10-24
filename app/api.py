from fastapi import APIRouter, HTTPException, Request
from typing import List, Optional
from app.models import Item, ItemCreate
from bson import ObjectId

router = APIRouter()


def _doc_to_item(doc: dict) -> Optional[Item]:
    """Convert a MongoDB document to an Item Pydantic model.

    Ensures the `_id` field is converted to a string so Pydantic can parse it
    with the alias defined in `Item`.
    """
    if not doc:
        return None
    if isinstance(doc.get("_id"), ObjectId):
        doc["_id"] = str(doc["_id"])
    return Item.parse_obj(doc)


@router.get("/items", response_model=List[Item])
async def list_items(request: Request):
    db = request.app.state.db
    cursor = db.items.find()
    docs = await cursor.to_list(length=100)
    return [_doc_to_item(d) for d in docs]


@router.post("/items", response_model=Item, status_code=201)
async def create_item(request: Request, payload: ItemCreate):
    db = request.app.state.db
    doc = payload.dict()
    result = await db.items.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return Item.parse_obj(doc)


@router.get("/items/{item_id}", response_model=Item)
async def get_item(request: Request, item_id: str):
    db = request.app.state.db
    try:
        oid = ObjectId(item_id)
    except Exception:
        # not a valid ObjectId; return 404
        raise HTTPException(status_code=404, detail="Not found")
    doc = await db.items.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return _doc_to_item(doc)
