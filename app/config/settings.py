from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Eleven"
    env: str = "development"

    postgres_user: str = "eleven"
    postgres_password: str = "eleven"
    postgres_db: str = "eleven"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    auth0_domain: str = ""
    auth0_audience: str = ""
    auth0_algorithms: str = "RS256"

    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""

    pitch_nearby_radius_meters: float = 250.0
    pitch_similar_centroid_meters: float = 15.0
    pitch_suggest_limit: int = 5

    model_config = SettingsConfigDict(env_file=".env")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def auth0_issuer(self) -> str:
        return f"https://{self.auth0_domain}/"

    @property
    def auth0_jwks_url(self) -> str:
        return f"https://{self.auth0_domain}/.well-known/jwks.json"

    @property
    def auth0_algorithms_list(self) -> list[str]:
        return [a.strip() for a in self.auth0_algorithms.split(",") if a.strip()]


settings = Settings()
