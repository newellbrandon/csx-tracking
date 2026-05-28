from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    MONGODB_URI: str
    CSX_DEMO_DB: str = "csx_demo"

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    SIM_INTERVAL_SECONDS: float = 5.0
    SIM_STEP_KM: float = 18.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
