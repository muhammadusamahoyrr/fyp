from pathlib import Path

from datetime import datetime, timezone

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# The widest cadence the scheduler may ever run at, and the widest it may run
# at WHILE REMINDERS ARE ENABLED. Two numbers because they answer two
# questions: the first is "is this a scheduler at all", the second is "can it
# still see a one-hour window". Named here so the validator, the scheduler and
# the readiness audit all cite the same figure instead of three copies of 30.
MAX_INTERVAL_MINUTES = 720
REMINDER_WINDOW_MINUTES = 60
MAX_REMINDER_INTERVAL_MINUTES = REMINDER_WINDOW_MINUTES // 2

# Mirrors `appointment_expiry_sweep.DEFAULT_LIMIT`. Stated as a number rather
# than imported because `app.core.config` must not import a service -- every
# service reads settings, and the cycle would be immediate. The test suite
# asserts the two agree, so the duplication cannot drift silently.
MAX_EXPIRY_BATCH = 200


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Trusted reverse proxies, as a comma-separated list of peer addresses
    # (decision D8). EMPTY BY DEFAULT, and the default is the safe one: with
    # nothing configured, `X-Forwarded-For` is ignored entirely and the client
    # IP is whatever the socket says.
    #
    # This exists because an evidence document must not assert a fact it cannot
    # support. Behind an unconfigured proxy every request appears to come from
    # the proxy, so recording that as "the IP the signer used" would be false;
    # and trusting the header without checking the peer lets any caller write
    # their own IP into the record. When neither is safe the IP is OMITTED --
    # see `client_ip`.
    trusted_proxies: str = ""

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

    # ── LOCAL ENGLISH OCR ─────────────────────────────────────────────────────
    # OFF by default. When off, nothing
    # spawns an OCR engine, no revision is written, and extraction behaves
    # byte-for-byte as it did before.
    #
    # The flag gates the RUN, not the storage schema: rows already written stay
    # readable, because turning a feature off must not make existing records
    # unreadable.
    #
    # When on, engine output is excluded from every analysis prompt until the
    # owning client reviews/corrects and confirms every OCR page. Confirmation
    # is hash-bound; only the separately stored confirmed value is analysed.
    # ── LAWYER WORKING HOURS ──────────────────────────────────────────────────
    # OFF by default, and narrowly scoped to BOOKING ACCEPTANCE.
    #
    # While off, booking behaves exactly as it did: any aligned future slot is
    # accepted, because every lawyer currently on the system signed up without
    # a schedule and turning this on for them would make them unbookable
    # overnight. Availability is still computed and returned — but it is
    # labelled unenforced, and a lawyer with no schedule is reported as
    # unconfigured rather than given invented hours.
    #
    # While on, a booking is refused when the lawyer has no configured schedule,
    # or when the requested time falls outside it. That is a real change to what
    # the API accepts, which is why it is a switch somebody throws rather than a
    # consequence of deploying.
    appointment_working_hours_enforced: bool = False

    # ── APPOINTMENT SCHEDULER ──────────────────────────────────────────────────
    # Both OFF by default, and independently. The reminder and outcome-nudge
    # mechanisms exist and are tested; nothing runs them until somebody turns
    # one of these on, per environment, deliberately.
    #
    # Enabling either sends messages to real people, so the defaults here are
    # the safety property — not a placeholder to be flipped by a deployment.
    appointment_reminders_enabled: bool = False
    appointment_outcome_nudges_enabled: bool = False

    # THE ACTIVATION INSTANT FOR OUTCOME NUDGES, and it is deliberately not
    # derivable from anything.
    #
    # A consultation is eligible for a nudge only if it became due at or after
    # this moment, which is what stops a first run notifying about every
    # unreported consultation in the product's history. Defaulting it to "when
    # this process started" would make the blast radius a property of the last
    # deployment — and a restart would silently move it, so a redeploy could
    # re-open a window somebody had already closed.
    #
    # Naive values are REFUSED rather than assumed to be UTC: "2026-01-01
    # 09:00" means different instants in different places, and guessing which
    # decides how much history gets messaged.
    appointment_outcome_nudges_activated_at: datetime | None = None

    # How often the scheduler wakes. Bounded at both ends: too short is a
    # thrash against the notification store, too long makes a T-1h reminder
    # arrive after the consultation.
    appointment_scheduler_interval_minutes: int = 15

    # Per-cycle caps, passed to the services as their `limit`. Conservative:
    # the first real run against an existing deployment meets the whole backlog
    # at once, and a batch that messages everybody simultaneously is an
    # incident whichever way the messages go.
    appointment_reminder_batch: int = 100
    appointment_outcome_nudge_batch: int = 25

    # THE EXPIRY MECHANISM. OFF, and the only flag here whose effect on a
    # client is irreversible: expiring a request terminates it, and there is
    # no transition out of EXPIRED.
    #
    # ONE FLAG, TWO CONSUMERS. It gates the sweep that retires lapsed requests
    # AND the confirmation path's refusal to accept one. They have to move
    # together: a sweep with no confirmation guard lets a lawyer confirm a
    # request the next sweep is about to retire, and a confirmation guard with
    # no sweep leaves a lapsed request neither confirmable nor expired --
    # stuck, still holding its slots, with no explanation for either party.
    # Two flags would make that second state reachable by setting one of them.
    appointment_expiry_enabled: bool = False

    # Deliberately smaller than the reminder and nudge caps. Each item here is
    # a request being terminated and a client being told so; the first
    # applying run against an existing deployment meets the whole history of
    # unanswered requests at once, and a cap is what stops that being one
    # event. The sweep refuses anything above its own DEFAULT_LIMIT of 200.
    appointment_expiry_batch: int = 50

    # ── DIY CONTRACT BUILDER ──────────────────────────────────────────────────
    # OFF. This parks the client-facing agreement wizard -- the NDA / lease /
    # employment template gallery and the create flow behind it.
    #
    # WHY IT IS PARKED AND NOT MERELY HIDDEN. All six templates were withdrawn
    # because the wording was United States contract boilerplate, unsuitable to
    # sign in Pakistan, and the backend already refuses any body still carrying
    # the withdrawal notice. So the builder cannot currently produce a valid
    # agreement at all: every path through it ends in a refusal, after four
    # steps of the user's work. Writing replacement templates is legal work
    # blocked on counsel, not engineering work.
    #
    # WHAT IT DOES NOT GATE, and must not. Engagement letters are a different
    # product sharing the same collection and UI: they are generated when a
    # client accepts a lawyer's fee terms, and they gate all billing. They are
    # created by `create_pending_engagement_letter` from inside
    # engagement_service, NOT through the HTTP route, so this flag leaves them
    # untouched. Listing, viewing, signing and declining stay available to
    # everyone whatever this is set to -- an agreement somebody is already a
    # party to must never become unreachable because a feature was parked.
    #
    # Turning it on requires counsel-reviewed templates first
    # (AGREEMENTS_PRODUCT_PLAN.md D1 / Phase 4.3), not just a deployment.
    agreements_diy_builder_enabled: bool = False

    english_ocr_enabled: bool = False
    # Identifier of the reviewed benchmark/evidence used to approve production
    # activation. Development may exercise the feature without one; production
    # may not turn it on with an untraceable "someone tested it" assertion.
    english_ocr_benchmark_id: str = ""

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

    @field_validator("appointment_outcome_nudges_activated_at")
    @classmethod
    def _activation_must_be_aware(cls, value):
        """Refuse a naive activation instant; normalise an aware one to UTC.

        A naive timestamp is not a moment — it is a wall-clock reading whose
        meaning depends on where it is read. Accepting one here would let the
        same configuration line mean different amounts of message history in
        different deployments.
        """
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "appointment_outcome_nudges_activated_at must include a UTC "
                "offset (e.g. 2026-10-01T00:00:00Z) — a naive timestamp does "
                "not identify an instant, and this value decides how much "
                "history gets notified")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _outcome_nudges_need_an_activation_instant(self):
        """FAIL CLOSED. Enabling nudges without a fixed activation instant
        would make the first run's scope whatever the clock happened to say."""
        if (self.appointment_outcome_nudges_enabled
                and self.appointment_outcome_nudges_activated_at is None):
            raise ValueError(
                "appointment_outcome_nudges_enabled requires "
                "appointment_outcome_nudges_activated_at — without a fixed "
                "instant the first run would decide for itself how much of "
                "the backlog to notify")
        return self

    @field_validator("appointment_scheduler_interval_minutes")
    @classmethod
    def _interval_is_sane(cls, value):
        if not 1 <= value <= MAX_INTERVAL_MINUTES:
            raise ValueError(
                "appointment_scheduler_interval_minutes must be between 1 and "
                f"{MAX_INTERVAL_MINUTES} — shorter thrashes the notification "
                "store, longer makes a T-1h reminder arrive after the "
                "consultation")
        return value

    @model_validator(mode="after")
    def _reminder_cadence_must_fit_the_shortest_window(self):
        """A cadence wider than half the narrowest reminder window is a miss.

        The T-1h window is ONE HOUR WIDE. A scheduler waking every 60 minutes
        gets exactly one opportunity inside it if the phase happens to line up,
        and none at all if it does not — an appointment can enter and leave the
        window between two ticks. That failure is silent and it is invisible in
        testing, because it depends on the offset between the wake-up phase and
        somebody's booking time.

        Capping at half the window guarantees at least two opportunities, so
        one missed or skipped tick still leaves a chance to send. It is the
        standard sampling argument and it is why the number is 30 rather than
        60: 60 is the width at which coverage depends on luck.

        IT APPLIES ONLY WHEN REMINDERS ARE ON. Outcome nudges chase a backlog
        that is hours to days old and have no window to miss, so a deployment
        running nudges alone keeps the full range — narrowing it there would be
        a restriction with nothing behind it.

        Checked HERE rather than in the loop. The loop reads this value once at
        startup; a check inside it would report a misconfiguration only after
        the process was already running on it, and only to a log nobody reads
        until a reminder is missing.
        """
        if (self.appointment_reminders_enabled
                and self.appointment_scheduler_interval_minutes
                > MAX_REMINDER_INTERVAL_MINUTES):
            raise ValueError(
                "appointment_reminders_enabled requires "
                "appointment_scheduler_interval_minutes <= "
                f"{MAX_REMINDER_INTERVAL_MINUTES} (currently "
                f"{self.appointment_scheduler_interval_minutes}) — the T-1h "
                "reminder window is 60 minutes wide, so a wider cadence can "
                "step over it entirely and the appointment goes unremind"
                "ed with nothing in the logs to say so")
        return self

    @field_validator("appointment_reminder_batch",
                     "appointment_outcome_nudge_batch")
    @classmethod
    def _batch_is_sane(cls, value):
        if not 1 <= value <= 500:
            raise ValueError("batch caps must be between 1 and 500")
        return value

    @field_validator("appointment_expiry_batch")
    @classmethod
    def _expiry_batch_is_conservative(cls, value):
        """A tighter bound than the other caps, and not by preference.

        `expire_lapsed_requests` refuses a limit above its own DEFAULT_LIMIT,
        so a larger value here would be accepted by settings and then rejected
        at the moment the sweep ran -- a misconfiguration that only appears
        once the feature is switched on, in a scheduled job, to a log.
        """
        if not 1 <= value <= MAX_EXPIRY_BATCH:
            raise ValueError(
                "appointment_expiry_batch must be between 1 and "
                f"{MAX_EXPIRY_BATCH} -- each row is somebody's request being "
                "terminated, and the sweep refuses a larger limit anyway")
        return value

    @model_validator(mode="after")
    def validate_production_transport(self):
        if self.app_env.lower() == "production" and not self.frontend_url.startswith("https://"):
            raise ValueError("FRONTEND_URL must use HTTPS in production")
        if (
            self.app_env.lower() == "production"
            and self.english_ocr_enabled
            and not self.english_ocr_benchmark_id.strip()
        ):
            raise ValueError(
                "ENGLISH_OCR_BENCHMARK_ID is required when English OCR is "
                "enabled in production"
            )
        return self


settings = Settings()
