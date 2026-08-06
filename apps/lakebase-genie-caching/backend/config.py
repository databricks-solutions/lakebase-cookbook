"""Configuration for the Lakebase Genie Caching.

All workspace-specific values are read from environment variables (set by
the databricks.yml config: block at deploy time).  Sensible defaults are
provided for universal values only (e.g. embedding model name, thresholds).
"""

import os
from dataclasses import dataclass, field


@dataclass
class GenieSpaceConfig:
    space_id: str
    title: str
    description: str = ""


def _parse_genie_spaces() -> list[GenieSpaceConfig]:
    """Parse GENIE_SPACE_IDS env var into GenieSpaceConfig list.

    Titles/descriptions are resolved later at startup via the Genie API.
    Until then, the space_id is used as a placeholder title.
    """
    raw = os.environ.get("GENIE_SPACE_IDS", "")
    return [
        GenieSpaceConfig(space_id=sid, title=sid)
        for sid in (s.strip() for s in raw.split(","))
        if sid
    ]


GENIE_SPACES: list[GenieSpaceConfig] = _parse_genie_spaces()


@dataclass
class GenieConfig:
    spaces: list[GenieSpaceConfig] = field(default_factory=lambda: list(GENIE_SPACES))
    warehouse_id: str = field(default_factory=lambda: os.environ.get("SQL_WAREHOUSE_ID", ""))


@dataclass
class LakebaseConfig:
    instance_name: str = field(default_factory=lambda: os.environ.get("DATABRICKS_LAKEBASE_INSTANCE", ""))
    endpoint_name: str = field(default_factory=lambda: os.environ.get("ENDPOINT_NAME", ""))
    project_name: str = field(default_factory=lambda: os.environ.get("LAKEBASE_PROJECT", ""))
    database_name: str = field(default_factory=lambda: os.environ.get("PGDATABASE", "databricks_postgres"))
    dns: str = field(default_factory=lambda: os.environ.get("PGHOST", ""))
    port: int = field(default_factory=lambda: int(os.environ.get("PGPORT", "5432")))
    sslmode: str = field(default_factory=lambda: os.environ.get("PGSSLMODE", "require"))

    @property
    def is_autoscaling(self) -> bool:
        return bool(self.endpoint_name or self.project_name)

    @property
    def resolved_endpoint_name(self) -> str:
        if self.endpoint_name:
            return self.endpoint_name
        if self.project_name:
            return f"projects/{self.project_name}/branches/production/endpoints/primary"
        return ""


@dataclass
class CacheConfig:
    similarity_threshold: float = 0.90
    answer_morph_threshold: float = 0.75
    top_k: int = 5
    max_age_days: int = 90
    stale_days: int = 7
    max_entries: int = 10000
    ttl_hours: int = 72
    parameterize_on_ingest: bool = True
    populate_params_on_query: bool = True



@dataclass
class MemoryConfig:
    top_k: int = 5
    similarity_threshold: float = 0.7
    max_age_days: int = 180
    score_threshold: float = 0.3
    decay_rate: float = 0.05
    blocklist_threshold: float = 0.95


@dataclass
class SessionConfig:
    """Conversation session retention.

    Sessions previously had no expiry, so rows accumulated indefinitely. 90 days
    keeps recent history browsable while bounding table growth.
    """
    max_age_days: int = int(os.environ.get("SESSION_MAX_AGE_DAYS", "90"))


@dataclass
class EmbeddingConfig:
    model_endpoint: str = "databricks-gte-large-en"
    dimensions: int = 1024


@dataclass
class LLMConfig:
    classifier_endpoint: str = field(
        default_factory=lambda: os.environ.get(
            "CLASSIFIER_LLM_ENDPOINT", "databricks-claude-haiku-4-5"
        )
    )
    assistant_endpoint: str = field(
        default_factory=lambda: os.environ.get(
            "ASSISTANT_LLM_ENDPOINT", "databricks-claude-sonnet-4"
        )
    )


@dataclass
class TraceArchiveConfig:
    """Delta table where the Trace Archive Job stores MLflow traces.

    catalog and schema have no defaults on purpose: they are workspace-specific,
    and a wrong-but-plausible default silently writes traces somewhere the
    deployer did not intend. Unset means the offline pipeline is disabled.
    """
    catalog: str = field(default_factory=lambda: os.environ.get("TRACE_ARCHIVE_CATALOG", ""))
    schema: str = field(default_factory=lambda: os.environ.get("TRACE_ARCHIVE_SCHEMA", ""))
    table_name: str = field(default_factory=lambda: os.environ.get("TRACE_ARCHIVE_TABLE", "mlflow_traces_archived"))

    @property
    def is_configured(self) -> bool:
        return bool(self.catalog and self.schema and self.table_name)

    @property
    def full_table_name(self) -> str:
        return f"`{self.catalog}`.`{self.schema}`.`{self.table_name}`"


@dataclass
class BatchJobConfig:
    """Databricks Job for batch pipelines (cache/memory/eviction).

    When a job ID or name is explicitly configured, the frontend pipeline
    buttons trigger the Databricks Job instead of running pipelines locally.
    """
    job_id: str = field(default_factory=lambda: os.environ.get("BATCH_JOB_ID", ""))
    job_name: str = field(default_factory=lambda: os.environ.get("BATCH_JOB_NAME", ""))

    @property
    def enabled(self) -> bool:
        return bool(self.job_id or self.job_name)


@dataclass
class TimeoutConfig:
    """Per-call timeouts, in seconds.

    These were previously inline magic numbers scattered across the pipeline
    (15 / 45 / 60), which made it impossible to tune latency in one place.
    """
    classifier_llm: int = int(os.environ.get("TIMEOUT_CLASSIFIER_LLM", "15"))
    assistant_llm: int = int(os.environ.get("TIMEOUT_ASSISTANT_LLM", "60"))
    supervisor_llm: int = int(os.environ.get("TIMEOUT_SUPERVISOR_LLM", "45"))
    genie_query: int = int(os.environ.get("TIMEOUT_GENIE_QUERY", "300"))
    cached_sql: int = int(os.environ.get("TIMEOUT_CACHED_SQL", "30"))
    permissions_api: int = int(os.environ.get("TIMEOUT_PERMISSIONS_API", "10"))


@dataclass
class AppConfig:
    genie: GenieConfig = field(default_factory=GenieConfig)
    lakebase: LakebaseConfig = field(default_factory=LakebaseConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    trace_archive: TraceArchiveConfig = field(default_factory=TraceArchiveConfig)
    batch_job: BatchJobConfig = field(default_factory=BatchJobConfig)
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))
    # When true, Genie calls and cached SQL refuse to run as the app's service
    # principal: a caller token must be present, so Unity Catalog decides what each
    # user sees. Off by default so the app works without user authorization, which
    # is an admin-gated Public Preview -- a cache that silently never serves looks
    # like a broken feature rather than a missing setting.
    #
    # Turn this ON before pointing the app at data where users have differing
    # access. The cache stores SQL only and re-executes on every hit, so with a
    # caller token present the warehouse enforces per-user access on each request.
    require_user_auth: bool = field(
        default_factory=lambda: os.environ.get("REQUIRE_USER_AUTH", "false").strip().lower() == "true"
    )
    mlflow_experiment_name: str = field(
        default_factory=lambda: os.environ.get("MLFLOW_EXPERIMENT_NAME", "/lakebase-genie-caching")
    )
    # Preferred over the name when set. The bundle passes the ID of the experiment
    # it created, which avoids a name lookup that fails whenever the bundle
    # prefixed the name (development mode) -- and avoids the app attempting to
    # create an experiment it has no permission to create.
    mlflow_experiment_id: str = field(
        default_factory=lambda: os.environ.get("MLFLOW_EXPERIMENT_ID", "")
    )

    def validate(self) -> list[str]:
        """Return human-readable problems with the current configuration.

        Called at startup so a misconfigured deployment says which env var is
        missing, instead of failing later with an opaque API error. Returns
        messages rather than raising: some gaps only disable a feature (the
        offline pipeline) and should not stop the app from serving.
        """
        problems: list[str] = []

        if not self.genie.warehouse_id:
            problems.append(
                "SQL_WAREHOUSE_ID is not set -- Genie queries and cached SQL cannot execute. "
                "Set the `warehouse_id` bundle variable."
            )
        if not self.genie.spaces:
            problems.append(
                "GENIE_SPACE_IDS is not set -- there are no Genie spaces to route to. "
                "Set the `genie_space_ids` bundle variable to one or more 32-hex space IDs."
            )
        if not self.lakebase.is_autoscaling and not self.lakebase.dns:
            problems.append(
                "No Lakebase target: set LAKEBASE_PROJECT (Autoscaling) or PGHOST. "
                "Without it the cache, memory, and session stores are unavailable."
            )
        if not self.trace_archive.is_configured:
            problems.append(
                "TRACE_ARCHIVE_CATALOG / TRACE_ARCHIVE_SCHEMA are not set -- the offline "
                "cache-promotion and memory-extraction pipelines are disabled. The online "
                "path still works."
            )

        if not 0.0 < self.cache.similarity_threshold <= 1.0:
            problems.append(
                f"cache.similarity_threshold must be in (0, 1]; got {self.cache.similarity_threshold}"
            )
        if not 0.0 < self.cache.answer_morph_threshold <= self.cache.similarity_threshold:
            problems.append(
                "cache.answer_morph_threshold must be in (0, similarity_threshold]; got "
                f"{self.cache.answer_morph_threshold} vs {self.cache.similarity_threshold}"
            )

        return problems


config = AppConfig()
