from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _strip(v: str | None) -> str | None:
    return "".join(v.split()) if isinstance(v, str) else v


class Settings(BaseSettings):
    """Runtime settings. Keys are whitespace-stripped (some secret stores pad them)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    opticodds_api_key: str = Field("", alias="OPTICODDS_API_KEY")
    oddspapi_api_key: str = Field("", alias="ODDSPAPI_API_KEY")
    sharpsports_api_key: str = Field("", alias="SHARPSPORTS_API_KEY")
    sharpsports_api_secret: str = Field("", alias="SHARPSPORTS_API_SECRET")

    opticodds_base: str = "https://api.opticodds.com/api/v3"
    oddspapi_base: str = "https://v5.oddspapi.io/en"
    oddspapi_ws: str = "wss://v5.oddspapi.io/ws"
    sharpsports_base: str = "https://api.sharpsports.io/v1"

    raw_dir: str = Field("./data/raw", alias="U3_RAW_DIR")
    gcs_bucket: str = Field("", alias="U3_GCS_BUCKET")
    clickhouse_url: str = Field("", alias="U3_CLICKHOUSE_URL")
    metrics_port: int = Field(0, alias="U3_METRICS_PORT")
    user_agent: str = "u3-ingest/0.1 (+https://github.com/u3/api)"

    @field_validator("opticodds_api_key", "oddspapi_api_key", "sharpsports_api_key", "sharpsports_api_secret", mode="before")
    @classmethod
    def _strip_keys(cls, v: str | None) -> str | None:
        return _strip(v)

    @property
    def sharpsports_token(self) -> str:
        """SharpSports: the private key unlocks /events, /prices and historicData; fall back to the public key."""
        return self.sharpsports_api_secret or self.sharpsports_api_key


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
