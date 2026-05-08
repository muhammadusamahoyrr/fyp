from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # MongoDB
    mongodb_url: str = "mongodb://localhost:27017"
    db_name: str = "attorney_ai"

    # JWT
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    # AES encryption for CNIC
    encryption_key: str

    # LLM
    gemini_api_key: str = ""
    groq_api_key: str = ""
    llm_provider: str = "gemini"

    # ChromaDB
    chroma_host: str = "chroma"
    chroma_port: int = 8001

    # Email
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = "noreply@attorney.ai"

    # App
    app_env: str = "development"
    frontend_url: str = "http://localhost:3000"


settings = Settings()
