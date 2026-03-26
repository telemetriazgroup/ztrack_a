from functools import lru_cache
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # App
    # development/testing → /docs, /redoc habilitados | production → deshabilitados
    app_env: Literal["production", "development", "testing"] = Field(
        default="development",
        validation_alias="APP_ENV",
    )
    # Override explícito: true = siempre mostrar /docs (ignora APP_ENV)
    enable_docs: bool = Field(default=False, validation_alias="ENABLE_DOCS")
    app_port: int = 9050
    app_host: str = "0.0.0.0"
    app_debug: bool = False

    # MongoDB
    # Nombres compatibles con el .env original (MONGO_DETAILS_OK, BD_DETAILS_OK)
    mongo_uri: str = Field(default="mongodb://localhost:27017", alias="MONGO_DETAILS_OK",
                           validation_alias="MONGO_DETAILS_OK")
    mongo_database: str = Field(default="ztrack_db", alias="BD_DETAILS_OK",
                                validation_alias="BD_DETAILS_OK")
    mongo_max_pool_size: int = 20
    mongo_min_pool_size: int = 5
    mongo_connect_timeout_ms: int = 5000
    mongo_server_selection_timeout_ms: int = 5000
    # Respaldo (opcional): misma estructura de colecciones; Starcool / Generador / Datos
    mongo_backup_uri: str = Field(default="", validation_alias="MONGO_BACKUP_URI")
    mongo_backup_database: str = Field(default="", validation_alias="MONGO_BACKUP_DB")

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0
    redis_max_connections: int = 20
    redis_auth_cache_ttl: int = 300

    # Batch Writer
    batch_size: int = 50
    batch_timeout_seconds: float = 2.0
    batch_worker_sleep_on_empty: float = 0.1

    # Seguridad
    enable_auth: bool = False      # False por defecto: compatibilidad con dispositivos legacy
    legacy_accept: bool = True
    max_payload_size_bytes: int = 16384

    # Zona horaria para fechas (Docker usa UTC; datos históricos en GMT-5)
    app_timezone: str = Field(default="America/Lima", validation_alias="APP_TIMEZONE")

    # Logging / Métricas
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "console"
    metrics_enabled: bool = True
    metrics_path: str = "/metrics"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def show_docs(self) -> bool:
        """True si /docs debe estar habilitado (ENABLE_DOCS o no producción)."""
        return self.enable_docs or not self.is_production

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # También soportar nombres nuevos directamente
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore",
        populate_by_name=True,
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
