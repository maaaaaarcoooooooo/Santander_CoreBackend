from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    PORTAL_BACKEND_URL: str = "http://localhost:8000"
    PORT: int = 8001
    CORS_ORIGINS: str = "http://localhost:5173"
    ALLOW_ORIGIN_REGEX: str | None = None

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def allow_origin_regex(self) -> str | None:
        if self.ALLOW_ORIGIN_REGEX and self.ALLOW_ORIGIN_REGEX.strip():
            return self.ALLOW_ORIGIN_REGEX.strip()
        return None


settings = Settings()
