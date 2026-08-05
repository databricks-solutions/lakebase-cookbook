"""Tests for configuration defaults and structure."""

from backend.config import (
    AppConfig,
    BatchJobConfig,
    CacheConfig,
    EmbeddingConfig,
    GenieConfig,
    LakebaseConfig,
    LLMConfig,
    MemoryConfig,
)


class TestAppConfig:
    def test_default_config_creation(self):
        config = AppConfig()
        assert isinstance(config.genie, GenieConfig)
        assert isinstance(config.lakebase, LakebaseConfig)
        assert isinstance(config.cache, CacheConfig)
        assert isinstance(config.memory, MemoryConfig)
        assert isinstance(config.embedding, EmbeddingConfig)
        assert isinstance(config.llm, LLMConfig)


class TestCacheConfig:
    def test_defaults(self):
        cfg = CacheConfig()
        assert 0.0 < cfg.similarity_threshold <= 1.0
        assert 0.0 < cfg.answer_morph_threshold <= 1.0
        assert cfg.answer_morph_threshold < cfg.similarity_threshold
        assert cfg.top_k >= 1
        assert cfg.ttl_hours > 0
        assert cfg.max_age_days > 0
        assert cfg.max_entries == 10000
        assert cfg.parameterize_on_ingest is True
        assert cfg.populate_params_on_query is True


class TestEmbeddingConfig:
    def test_defaults(self):
        cfg = EmbeddingConfig()
        assert cfg.model_endpoint == "databricks-gte-large-en"
        assert cfg.dimensions == 1024


class TestLLMConfig:
    def test_defaults(self):
        cfg = LLMConfig()
        assert cfg.classifier_endpoint
        assert cfg.assistant_endpoint


class TestMemoryConfig:
    def test_defaults(self):
        cfg = MemoryConfig()
        assert cfg.top_k == 5
        assert cfg.similarity_threshold == 0.7
        assert cfg.decay_rate == 0.05


class TestLakebaseConfig:
    def test_defaults(self):
        cfg = LakebaseConfig()
        assert cfg.port == 5432
        assert cfg.sslmode == "require"
        assert cfg.database_name == "databricks_postgres"

    def test_autoscaling_project_resolves_default_endpoint(self, monkeypatch):
        monkeypatch.setenv("LAKEBASE_PROJECT", "lakebase-genie-caching")
        monkeypatch.delenv("ENDPOINT_NAME", raising=False)

        cfg = LakebaseConfig()

        assert cfg.is_autoscaling is True
        assert (
            cfg.resolved_endpoint_name
            == "projects/lakebase-genie-caching/branches/production/endpoints/primary"
        )

    def test_endpoint_override_wins_over_project(self, monkeypatch):
        monkeypatch.setenv("LAKEBASE_PROJECT", "lakebase-genie-caching")
        monkeypatch.setenv(
            "ENDPOINT_NAME",
            "projects/custom/branches/production/endpoints/primary",
        )

        cfg = LakebaseConfig()

        assert cfg.resolved_endpoint_name == "projects/custom/branches/production/endpoints/primary"


class TestBatchJobConfig:
    def test_disabled_without_explicit_env(self, monkeypatch):
        monkeypatch.delenv("BATCH_JOB_ID", raising=False)
        monkeypatch.delenv("BATCH_JOB_NAME", raising=False)

        cfg = BatchJobConfig()

        assert cfg.enabled is False

    def test_enabled_with_job_name_env(self, monkeypatch):
        monkeypatch.delenv("BATCH_JOB_ID", raising=False)
        monkeypatch.setenv("BATCH_JOB_NAME", "lakebase-genie-caching-batch")

        cfg = BatchJobConfig()

        assert cfg.enabled is True


class TestGenieConfig:
    def test_defaults_empty_spaces(self):
        cfg = GenieConfig()
        assert isinstance(cfg.spaces, list)

    def test_warehouse_id_type(self):
        cfg = GenieConfig()
        assert isinstance(cfg.warehouse_id, str)
