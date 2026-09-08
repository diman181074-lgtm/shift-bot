from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    database_url: str = "postgresql+asyncpg://shiftbot:shiftbot@db:5432/shiftbot"
    host: str = "0.0.0.0"
    port: int = 8000
    petrogradskaya_chat_id: int | None = None
    mayakovskaya_chat_id: int | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def __init__(self, **data):
        super().__init__(**data)
        if self.database_url.startswith("postgresql://"):
            self.database_url = "postgresql+asyncpg://" + self.database_url[len("postgresql://"):]
        elif self.database_url.startswith("postgres://"):
            self.database_url = "postgresql+asyncpg://" + self.database_url[len("postgres://"):]


settings = Settings()
