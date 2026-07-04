from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    description="AI-powered FX and payments intelligence demo platform.",
    version="0.1.0",
)

app.include_router(router, prefix="/api")
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
