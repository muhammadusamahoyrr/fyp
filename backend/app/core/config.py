from pathlib import Path

from pydantic import field_validator, model_validator
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

    # Lawyer vector-index reconciliation sweep. Declared HERE, not read straight
    # off the environment: settings is a pydantic model, so `getattr(settings,
    # "lawyer_reconcile_hours", 6)` on an undeclared name silently returns the
    # default forever and the operator's env var is ignored with no error. The
    # sweep is cheap when the index already agrees, so 6h is a fine default.
    lawyer_reconcile_hours: int = 6

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

    # ── DOCUMENTS_V2 — immutable document/revision model ──────────────────────
    # OFF by default. When off, every drafting path is byte-for-byte the legacy
    # path; the V2 collections, artifact store, reconciler and compat reader are
    # all dormant. Flipped only after the Stage-4 migration lands. See the
    # drafting remediation plan (v5 §0, v5.1) for the full contract.
    documents_v2: bool = False

    # Retention DELETION for V2 documents — a SEPARATE, independently approved
    # switch (v5 §12 / v5.1). Off by default: retention reports counts, but
    # nothing is destroyed until this is explicitly turned on. Deletion is
    # tombstone-first and crash-safe (services/document_deletion.py).
    documents_v2_deletion_enabled: bool = False

    # Retention DELETION for intakes and their uploaded evidence — its own
    # switch, deliberately not shared with the V2 one above. The two stores hold
    # different things and were approved separately; one flag would mean turning
    # on evidence destruction as a side effect of a documents decision.
    #
    # Off by default: the planner reports counts and the admin route is dry-run,
    # but nothing is destroyed until this is explicitly turned on. Deletion is
    # tombstone-first and crash-safe (services/intake_deletion.py).
    intake_deletion_enabled: bool = False

    # ── ENGLISH OCR (Milestone 3A) ────────────────────────────────────────────
    # OFF by default, and this milestone does not turn it on. When off, nothing
    # spawns an OCR engine, no revision is written, and extraction behaves
    # byte-for-byte as it did before.
    #
    # The flag gates the RUN, not the storage schema: rows already written stay
    # readable, because turning a feature off must not make existing records
    # unreadable.
    #
    # Even when on, OCR output is `ocr_completed_unconfirmed` and is excluded
    # from every analysis prompt. A second, separately approved step is what
    # allows confirmed text into analysis — see the UI-confirmation milestone.
    english_ocr_enabled: bool = False

    @field_validator("secret_key")
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        if len(value) < 32 or value.lower().startswith("change-this"):
            raise ValueError("SECRET_KEY must be a non-placeholder value of at least 32 characters")
        return value

    @field_validator("algorithm")
    @classmethod
    def validate_jwt_algorithm(cls, value: str) -> str:
        # This application uses one symmetric key. Refusing algorithm drift is
        # safer than accepting an arbitrary value from deployment config.
        if value != "HS256":
            raise ValueError("ALGORITHM must be HS256")
        return value

    @field_validator("access_token_expire_minutes", "refresh_token_expire_days")
    @classmethod
    def validate_token_lifetime(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("token lifetimes must be positive")
        return value

    @model_validator(mode="after")
    def validate_production_transport(self):
        if self.app_env.lower() == "production" and not self.frontend_url.startswith("https://"):
            raise ValueError("FRONTEND_URL must use HTTPS in production")
        return self


settings = Settings()
