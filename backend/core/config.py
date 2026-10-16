from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    CORS_ORIGINS: str = ""
    DATABASE_URL: str

    model_config = {"env_file": ".env"}


settings = Settings()
