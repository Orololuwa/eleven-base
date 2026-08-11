from fastapi import FastAPI

from app.config.settings import settings
from app.routes.base import router

app = FastAPI(
    title=settings.app_name,
    description=f"{settings.app_name} API",
    version="0.1.0",
)

app.include_router(router)


@app.get("/")
def root():
    return {"message": f"{settings.app_name} API is running"}
