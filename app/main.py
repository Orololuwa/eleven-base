from fastapi import FastAPI

from app.config.settings import settings
from app.routes.base import router as base_router
from app.routes.me import router as me_router
from app.routes.profiles import router as profiles_router

app = FastAPI(
    title=settings.app_name,
    description=f"{settings.app_name} API",
    version="0.1.0",
)

app.include_router(base_router)
app.include_router(me_router)
app.include_router(profiles_router)


@app.get("/")
def root():
    return {"message": f"{settings.app_name} API is running"}
