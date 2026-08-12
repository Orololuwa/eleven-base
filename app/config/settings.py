from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Eleven"
    env: str = "development"

    postgres_user: str = "eleven"
    postgres_password: str = "eleven"
    postgres_db: str = "eleven"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    class Config:
        env_file = ".env"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
