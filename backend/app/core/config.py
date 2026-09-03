from pathlib import Path

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
    # Second Groq account, tried when the first is rate-limited. Groq's free tier
    # caps tokens per DAY per model (gpt-oss-20b: 200,000), and the fast tier is
    # what the graph leans on — query expansion, the retrieval grader and the
    # hallucination judge all run there, so a day's traffic exhausts it while the
    # main tier still has budget. Before this, that exhaustion fell through to
    # OpenRouter, which has no credit, and the 402 killed the whole graph run.
    # Optional: unset simply drops out of the chain like any unconfigured key.
    groq_api_key_2: str = ""
    openrouter_api_key: str = ""
    llm_provider: str = "groq"

    # Local Ollama. The model must actually be pulled — a name that isn't
    # installed fails at request time, and with a cloud key present that
    # failure is invisible: the chain silently falls through to a paid
    # provider. Set llm_local_only=true to make that impossible.
    ollama_model: str = "qwen2.5:7b"
    ollama_fast_model: str = ""      # blank = use ollama_model for both tiers
    ollama_base_url: str = "http://127.0.0.1:11434"
    llm_local_only: bool = False     # true = never call a paid provider

    # ChromaDB
    chroma_host: str = "chroma"
    chroma_port: int = 8001

    # Redis — empty = disabled (in-process fallback for WS fan-out, scheduler
    # locks, caching, and rate-limiting). Set for multi-worker deployments.
    # When set, also configure the server with `maxmemory-policy allkeys-lru`
    # so the caches below can be evicted under memory pressure.
    redis_url: str = ""

    # Cache TTLs (seconds). Safety net — the AI cache also invalidates on
    # embedding/chunking/collection version changes before TTL.
    cache_result_ttl: int = 600       # full-pipeline result cache (10 min)
    cache_chunk_ttl: int = 300        # retrieval chunk cache (5 min)
    embedding_cache_ttl: int = 3600   # per-session intent embeddings (1 hour)

    # Email
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = "noreply@attorney.ai"


    # Cause-list scheduler
    causelist_check_hours: int = 6

    # Citator ingest streaming (Redis Streams; requires Redis 5.0+, and the
    # XAUTOCLAIM-based recovery of dead consumers needs 6.2+). Consumer-group
    # names are fixed in code (parse/embed); these only tune throughput/recovery.
    citator_stream_maxlen: int = 10000       # ~MAXLEN cap per stream (approx trim)
    citator_block_ms: int = 5000             # XREADGROUP BLOCK timeout (ms)
    citator_claim_min_idle_ms: int = 60000   # reclaim entries idle > this (dead consumer)
    citator_batch: int = 10                  # entries read per pass
    citator_max_deliveries: int = 5          # over this → dead-letter (judgment.dead)

    # Payments (Safepay). Empty keys + payments_dry_run=True → the MockProvider
    # handles the full checkout/webhook loop locally, so the whole pay flow is
    # demoable without any merchant credentials.
    safepay_api_key: str = ""
    safepay_secret_key: str = ""
    safepay_webhook_secret: str = ""
    safepay_env: str = "sandbox"          # sandbox | production
    payments_dry_run: bool = True
    platform_take_rate: float = 0.05      # platform's transaction-fee share (5%)
    fee_request_expiry_days: int = 14     # unpaid fee requests expire after this

    # Logging
    log_level: str = "INFO"
    # None → auto: structured JSON in production, human-readable pretty locally.
    # Set explicitly (LOG_JSON=true/false) to override.
    log_json: bool | None = None

    # App
    app_env: str = "development"
    frontend_url: str = "http://localhost:3000"
    cors_origins: str = ""            # extra allowed origins, comma-separated
    run_schedulers: bool = True       # in-process schedulers; disable on all but one worker
    # How often each worker checks the provenance outbox. Cheap when idle:
    # one indexed query that matches nothing.
    provenance_relay_seconds: int = 30
    # Single absolute root for all generated + uploaded files.
    upload_root: str = str(Path(__file__).resolve().parents[2] / "uploads")


settings = Settings()
