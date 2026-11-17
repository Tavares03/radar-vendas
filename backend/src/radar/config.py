"""Configuração do Radar de Vendas.

Tudo vem de variáveis de ambiente com prefixo ``RADAR_`` (ou de um arquivo ``.env``). As chaves de
LLM também aceitam os nomes usuais sem prefixo (``GROQ_API_KEY``, ``GEMINI_API_KEY``…).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

#: Segredo usado só em desenvolvimento. Em produção a aplicação se recusa a subir com ele.
DEV_SECRET_KEY = "dev-inseguro-troque-por-um-segredo-de-32-bytes-ou-mais"  # noqa: S105

CsvList = Annotated[list[str], NoDecode]


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _alias(name: str) -> AliasChoices:
    return AliasChoices(f"RADAR_{name}", name)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RADAR_",
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # ------------------------------------------------------------ geral
    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool | None = None  # None = JSON fora de dev
    public_base_url: str = "http://localhost:3000"

    # ------------------------------------------------------------ segurança
    secret_key: SecretStr = SecretStr(DEV_SECRET_KEY)
    jwt_ttl_minutes: int = 12 * 60
    cookie_name: str = "radar_session"
    cookie_secure: bool = False
    cors_origins: CsvList = Field(default_factory=list)
    rate_limit_per_minute: int = 240
    login_rate_limit_per_minute: int = 10
    allow_signup: bool = False
    webhook_allow_private_hosts: bool = False
    metrics_token: SecretStr | None = None

    # ------------------------------------------------------------ armazenamento
    database_url: str = "sqlite:///./data/radar.db"
    redis_url: str = "redis://localhost:6379/0"
    #: inline: thread na API (modo leve); postgres: tabela no banco + ``radar worker`` (Compose);
    #: rq: Valkey/Redis + ``radar worker``; sync: na hora, na mesma thread (testes).
    queue_mode: Literal["inline", "postgres", "rq", "sync"] = "inline"
    data_dir: Path = Path("./data")
    models_dir: Path = Path("./models")
    playbooks_dir: Path | None = None
    #: Amostras sintéticas (demonstração). Padrão: ``data/samples`` do repositório.
    samples_dir: Path | None = None

    # ------------------------------------------------------------ upload
    max_upload_mb: int = 200
    max_zip_uncompressed_mb: int = 1024
    max_zip_files: int = 5000
    max_zip_ratio: int = 200
    max_messages_per_conversation: int = 20000

    # ------------------------------------------------------------ transcrição
    transcription_enabled: bool = True
    whisper_model: str = "small"
    whisper_device: Literal["cpu", "cuda", "auto"] = "cpu"
    whisper_compute_type: str = "int8"
    max_audio_minutes: int = 30

    # ------------------------------------------------------------ modelos próprios
    # "auto": usa a pasta local em models_dir se existir; senão o id do Hub, se configurado.
    # "off": desliga a camada. Qualquer outro valor é um caminho local ou um id do Hugging Face.
    ner_model: str = "auto"
    classifier_model: str = "auto"
    embedding_model: str = "auto"
    ner_hub_id: str = ""
    classifier_hub_id: str = ""
    embedding_hub_id: str = "intfloat/multilingual-e5-small"
    #: Threads do ONNX Runtime por modelo (0 = o padrão dele, um por núcleo físico).
    ml_threads: int = Field(default=0, ge=0, le=64)

    # ------------------------------------------------------------ LLM
    # cloud: usa a cadeia inteira; local: só provedores locais (nada sai da máquina); off: sem LLM.
    llm_mode: Literal["cloud", "local", "off"] = "cloud"
    llm_providers: CsvList = Field(
        default_factory=lambda: ["groq", "gemini", "openrouter", "ollama"]
    )
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    llm_cache_ttl_seconds: int = 7 * 24 * 3600
    llm_max_conversation_tokens: int = 3500
    #: Teto da resposta. Nos modelos de raciocínio (gpt-oss) o raciocínio também conta aqui.
    llm_max_output_tokens: int = 2400
    #: Com todos os provedores no limite de taxa, quanto o worker espera pelo primeiro que liberar
    #: antes de gravar a análise sem LLM (0 = não espera).
    llm_throttle_wait_seconds: float = 65.0

    groq_api_key: SecretStr | None = Field(default=None, validation_alias=_alias("GROQ_API_KEY"))
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_requests_per_minute: int = 20
    groq_tokens_per_minute: int = 8000
    #: Só para modelos gpt-oss: low | medium | high (vazio = padrão do provedor, medium). Com
    #: medium o raciocínio consome quase todo o teto de resposta e o JSON sai cortado.
    groq_reasoning_effort: str = "low"

    gemini_api_key: SecretStr | None = Field(
        default=None, validation_alias=_alias("GEMINI_API_KEY")
    )
    gemini_model: str = "gemini-flash-lite-latest"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_requests_per_minute: int = 10
    gemini_tokens_per_minute: int = 200_000

    openrouter_api_key: SecretStr | None = Field(
        default=None, validation_alias=_alias("OPENROUTER_API_KEY")
    )
    openrouter_model: str = "google/gemma-4-31b-it:free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_requests_per_minute: int = 15
    openrouter_tokens_per_minute: int = 100_000

    ollama_base_url: str = ""
    ollama_model: str = "qwen3:4b"
    ollama_requests_per_minute: int = 600
    ollama_tokens_per_minute: int = 10_000_000

    # ------------------------------------------------------------ WhatsApp ao vivo (Evolution API)
    #: Endereço da Evolution API (vazio = integração desligada). No Compose: http://evolution:8080
    evolution_url: str = ""
    evolution_api_key: SecretStr | None = None
    #: Por onde a Evolution alcança esta API para entregar as mensagens (rede interna do Compose).
    evolution_webhook_base_url: str = "http://api:8000"
    #: A análise de uma conversa ao vivo roda depois deste tempo sem mensagens novas...
    whatsapp_idle_minutes: int = Field(default=30, ge=1)
    #: ...ou, numa conversa que não para, no máximo a cada este intervalo.
    whatsapp_max_wait_minutes: int = Field(default=180, ge=5)

    # ------------------------------------------------------------ notificações
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr | None = None
    smtp_from: str = "Radar de Vendas <radar@localhost>"
    smtp_starttls: bool = True
    telegram_bot_token: SecretStr | None = None

    # ------------------------------------------------------------ primeiro uso
    bootstrap_tenant_name: str = ""
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: SecretStr | None = None
    #: Carrega a empresa de demonstração na primeira subida, se o banco não tiver usuários
    #: (nunca em produção). Sem ``demo_password``, a senha é sorteada e sai no log da API.
    seed_demo: bool = False
    demo_password: SecretStr | None = None

    # ------------------------------------------------------------ padrões de retenção (dias)
    default_retention_raw_days: int = 90
    default_retention_media_days: int = 30

    @field_validator("cors_origins", "llm_providers", mode="before")
    @classmethod
    def _csv(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator(
        "groq_api_key", "gemini_api_key", "openrouter_api_key", "evolution_api_key", mode="before"
    )
    @classmethod
    def _strip_key(cls, value: object) -> object:
        # Chave colada de um arquivo do Windows traz "\r" e espaços: viraria um cabeçalho
        # Authorization inválido, que aparece como "falha de conexão".
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def _guard_production(self) -> Settings:
        if self.environment == "prod":
            secret = self.secret_key.get_secret_value()
            if secret == DEV_SECRET_KEY or len(secret) < 32:
                raise ValueError(
                    "RADAR_SECRET_KEY precisa ser um segredo próprio com 32+ caracteres em produção. "
                    'Gere um com: python -c "import secrets; print(secrets.token_urlsafe(48))"'
                )
        return self

    # ------------------------------------------------------------ derivados
    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def json_logs(self) -> bool:
        return self.environment != "dev" if self.log_json is None else self.log_json

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    if os.environ.get("RADAR_DISABLE_ENV_FILE"):
        # Testes: só variáveis de ambiente, sem ler o .env de quem está desenvolvendo.
        return Settings(_env_file=None)
    return Settings()


def reset_settings_cache() -> None:
    """Descarta a configuração em cache (usado em testes)."""
    get_settings.cache_clear()
