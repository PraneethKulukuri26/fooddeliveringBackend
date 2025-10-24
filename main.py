import os
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
from app.api import router as api_router
from app.auth import router as auth_router
import logging

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "backend3")

app = FastAPI(title="backend3 API", version="0.1.0")
app.include_router(api_router, prefix="/api")
app.include_router(auth_router, prefix="/auth")


@app.on_event("startup")
async def startup_db_client():
    # create motor client and attach DB to app.state
    app.state.mongo_client = AsyncIOMotorClient(MONGO_URI)
    app.state.db = app.state.mongo_client[MONGO_DB]
    # ensure the database/collection exists by writing a small seed document if needed
    try:
        dbs = await app.state.mongo_client.list_database_names()
        if MONGO_DB not in dbs:
            logging.info("Database '%s' not found; creating and seeding...", MONGO_DB)
            await app.state.db.items.insert_one({"name": "_init", "description": "created by startup seed"})
        else:
            # if DB exists but collection empty, seed a document to ensure visibility
            count = await app.state.db.items.count_documents({})
            if count == 0:
                logging.info("Database '%s' exists but has no items; inserting seed document.", MONGO_DB)
                await app.state.db.items.insert_one({"name": "_init", "description": "created by startup seed"})
        # ensure indexes for users collection
        try:
            await app.state.db.users.create_index("email", unique=True)
            # google_id is optional, use sparse index
            await app.state.db.users.create_index("google_id", unique=True, sparse=True)
        except Exception:
            logging.exception("Failed to create indexes on users collection")
    except Exception:
        logging.exception("Failed to ensure MongoDB '%s' exists during startup", MONGO_DB)


@app.on_event("shutdown")
async def shutdown_db_client():
    app.state.mongo_client.close()


@app.get("/")
async def root():
    return {"message": "Hello from backend3"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8787"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
