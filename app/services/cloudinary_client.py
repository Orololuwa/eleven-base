import time

import cloudinary
import cloudinary.uploader
from cloudinary.utils import api_sign_request

from app.config.settings import settings


def _configure() -> None:
    if not (
        settings.cloudinary_cloud_name
        and settings.cloudinary_api_key
        and settings.cloudinary_api_secret
    ):
        raise RuntimeError(
            "CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and "
            "CLOUDINARY_API_SECRET must be set"
        )
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )


def generate_upload_signature(*, folder: str) -> dict:
    _configure()
    timestamp = int(time.time())
    params_to_sign = {"timestamp": timestamp, "folder": folder}
    signature = api_sign_request(params_to_sign, settings.cloudinary_api_secret)
    return {
        "signature": signature,
        "timestamp": timestamp,
        "api_key": settings.cloudinary_api_key,
        "cloud_name": settings.cloudinary_cloud_name,
        "folder": folder,
    }


def destroy_asset(public_id: str) -> None:
    _configure()
    cloudinary.uploader.destroy(public_id, invalidate=True)
