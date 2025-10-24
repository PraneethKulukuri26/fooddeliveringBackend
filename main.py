from fastapi import FastAPI
from app.api import router as api_router

app = FastAPI(title="backend3 API", version="0.1.0")
app.include_router(api_router, prefix="/api")

@app.get("/")
def root():
    return {"message": "Hello from backend3"}
