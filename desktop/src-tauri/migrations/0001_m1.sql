CREATE TABLE research_project (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
) STRICT;

INSERT INTO research_project(id, name, created_at_ms)
VALUES ('00000000-0000-4000-8000-000000000001', 'Default research project', 0);

CREATE TABLE budget (
    id TEXT PRIMARY KEY,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('DEFAULT', 'PROJECT', 'RUN')),
    scope_id TEXT,
    warning_micro_usd INTEGER NOT NULL CHECK (warning_micro_usd >= 0),
    hard_micro_usd INTEGER NOT NULL CHECK (hard_micro_usd >= warning_micro_usd),
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    created_at_ms INTEGER NOT NULL,
    CHECK ((scope_type = 'DEFAULT' AND scope_id IS NULL) OR (scope_type != 'DEFAULT' AND scope_id IS NOT NULL)),
    UNIQUE (scope_type, scope_id)
) STRICT;

INSERT INTO budget(id, scope_type, scope_id, warning_micro_usd, hard_micro_usd, enabled, created_at_ms)
VALUES ('00000000-0000-4000-8000-000000000002', 'DEFAULT', NULL, 250000, 500000, 1, 0);

INSERT INTO budget(id, scope_type, scope_id, warning_micro_usd, hard_micro_usd, enabled, created_at_ms)
VALUES ('00000000-0000-4000-8000-000000000003', 'PROJECT', '00000000-0000-4000-8000-000000000001', 1000000, 2000000, 1, 0);

CREATE TABLE provider_policy (
    provider TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    kill_switch_reason TEXT,
    policy_class TEXT NOT NULL,
    evidence_ttl_seconds INTEGER NOT NULL CHECK (evidence_ttl_seconds > 0),
    refresh_after_seconds INTEGER NOT NULL CHECK (refresh_after_seconds > 0),
    purge_after_seconds INTEGER NOT NULL CHECK (purge_after_seconds >= evidence_ttl_seconds),
    deletion_after_seconds INTEGER CHECK (deletion_after_seconds IS NULL OR deletion_after_seconds >= evidence_ttl_seconds),
    max_requests_per_run INTEGER NOT NULL CHECK (max_requests_per_run >= 0),
    max_tool_calls_per_run INTEGER NOT NULL CHECK (max_tool_calls_per_run >= 0),
    max_input_tokens_per_run INTEGER NOT NULL CHECK (max_input_tokens_per_run >= 0),
    max_output_tokens_per_run INTEGER NOT NULL CHECK (max_output_tokens_per_run >= 0),
    retention_summary TEXT NOT NULL,
    data_use_summary TEXT NOT NULL,
    no_storage_mode TEXT NOT NULL,
    privacy_mode TEXT NOT NULL,
    provider_config_json TEXT NOT NULL CHECK (json_valid(provider_config_json)),
    registry_version TEXT NOT NULL,
    source_url TEXT NOT NULL,
    review_artifact_path TEXT NOT NULL,
    review_artifact_sha256 TEXT NOT NULL CHECK (length(review_artifact_sha256) = 64),
    checked_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL CHECK (expires_at_ms > checked_at_ms),
    CHECK (enabled = 0 OR kill_switch_reason IS NULL)
) STRICT;

CREATE TABLE price_card (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    source_url TEXT NOT NULL,
    currency TEXT NOT NULL CHECK (currency = 'USD'),
    unit_prices_json TEXT NOT NULL CHECK (json_valid(unit_prices_json)),
    effective_at_ms INTEGER NOT NULL,
    checked_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL CHECK (expires_at_ms > checked_at_ms),
    review_artifact_path TEXT NOT NULL,
    review_artifact_sha256 TEXT NOT NULL CHECK (length(review_artifact_sha256) = 64),
    UNIQUE (provider, model, review_artifact_sha256)
) STRICT;

CREATE TABLE provider_model_preflight (
    provider TEXT NOT NULL,
    configured_model TEXT NOT NULL,
    resolved_model TEXT,
    available INTEGER NOT NULL CHECK (available IN (0, 1)),
    retention_mode TEXT NOT NULL,
    data_use_mode TEXT NOT NULL,
    no_storage_mode TEXT NOT NULL,
    privacy_mode TEXT NOT NULL,
    checked_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL CHECK (expires_at_ms > checked_at_ms),
    CHECK (available = (resolved_model IS NOT NULL)),
    PRIMARY KEY (provider, configured_model)
) STRICT;

CREATE TABLE cache_entry (
    provider TEXT NOT NULL,
    namespace TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    input_sha256 TEXT NOT NULL CHECK (length(input_sha256) = 64),
    output_sha256 TEXT NOT NULL CHECK (length(output_sha256) = 64),
    schema_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    policy_class TEXT NOT NULL,
    contract_json TEXT NOT NULL CHECK (json_valid(contract_json)),
    created_at_ms INTEGER NOT NULL,
    accessed_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    purge_at_ms INTEGER,
    state TEXT NOT NULL CHECK (state IN ('VALID', 'STALE', 'PURGED')),
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    lease_owner TEXT,
    lease_expires_at_ms INTEGER,
    CHECK ((lease_owner IS NULL) = (lease_expires_at_ms IS NULL)),
    PRIMARY KEY (namespace, cache_key)
) STRICT;

CREATE TABLE cache_flight (
    namespace TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    input_sha256 TEXT NOT NULL CHECK (length(input_sha256) = 64),
    lease_owner TEXT NOT NULL,
    lease_expires_at_ms INTEGER NOT NULL,
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY (namespace, cache_key)
) STRICT;

CREATE TABLE cost_preview (
    consent_token TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES research_project(id) ON DELETE RESTRICT,
    run_scope_key TEXT NOT NULL,
    input_sha256 TEXT NOT NULL CHECK (length(input_sha256) = 64),
    normalized_intent_json TEXT NOT NULL CHECK (json_valid(normalized_intent_json)),
    plan_sha256 TEXT NOT NULL CHECK (length(plan_sha256) = 64),
    plan_contract_json TEXT NOT NULL CHECK (json_valid(plan_contract_json)),
    maximum_micro_usd INTEGER NOT NULL CHECK (maximum_micro_usd >= 0),
    already_committed_micro_usd INTEGER NOT NULL CHECK (already_committed_micro_usd >= 0),
    run_hard_limit_micro_usd INTEGER NOT NULL CHECK (run_hard_limit_micro_usd >= 0),
    project_hard_limit_micro_usd INTEGER NOT NULL CHECK (project_hard_limit_micro_usd >= 0),
    effective_hard_limit_micro_usd INTEGER NOT NULL CHECK (effective_hard_limit_micro_usd >= 0),
    expires_at_ms INTEGER NOT NULL,
    consumed_at_ms INTEGER,
    created_at_ms INTEGER NOT NULL,
    UNIQUE (project_id, input_sha256, plan_sha256, created_at_ms)
) STRICT;

CREATE TABLE planned_provider_call (
    id TEXT PRIMARY KEY,
    consent_token TEXT NOT NULL REFERENCES cost_preview(consent_token) ON DELETE CASCADE,
    provider_run_id TEXT UNIQUE,
    display_order INTEGER NOT NULL CHECK (display_order >= 0),
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    configured_model TEXT,
    resolved_model TEXT,
    price_card_id TEXT REFERENCES price_card(id) ON DELETE RESTRICT,
    reservation_micro_usd INTEGER NOT NULL CHECK (reservation_micro_usd >= 0),
    cost_kind TEXT NOT NULL CHECK (cost_kind IN ('PAID_CLOUD', 'FREE_METADATA', 'LOCAL_CACHE')),
    cache_status TEXT NOT NULL CHECK (cache_status IN ('MISS', 'HIT', 'STALE')),
    cache_namespace TEXT,
    cache_key TEXT,
    cache_input_sha256 TEXT CHECK (cache_input_sha256 IS NULL OR length(cache_input_sha256) = 64),
    cache_output_sha256 TEXT CHECK (cache_output_sha256 IS NULL OR length(cache_output_sha256) = 64),
    cache_schema_version TEXT,
    cache_model_version TEXT,
    cache_prompt_version TEXT,
    cache_policy_class TEXT,
    retention_summary TEXT NOT NULL,
    data_use_summary TEXT NOT NULL,
    no_storage_mode TEXT NOT NULL,
    privacy_mode TEXT NOT NULL,
    cheaper_alternative TEXT NOT NULL,
    requires_live_call INTEGER NOT NULL CHECK (requires_live_call IN (0, 1)),
    max_requests INTEGER NOT NULL CHECK (max_requests >= 0),
    max_tool_calls INTEGER NOT NULL CHECK (max_tool_calls >= 0),
    max_input_tokens INTEGER NOT NULL CHECK (max_input_tokens >= 0),
    max_output_tokens INTEGER NOT NULL CHECK (max_output_tokens >= 0),
    allow_one_repair INTEGER NOT NULL CHECK (allow_one_repair IN (0, 1)),
    provider_config_json TEXT NOT NULL CHECK (json_valid(provider_config_json)),
    policy_class TEXT NOT NULL,
    evidence_ttl_seconds INTEGER NOT NULL CHECK (evidence_ttl_seconds > 0),
    refresh_after_seconds INTEGER NOT NULL CHECK (refresh_after_seconds > 0),
    purge_after_seconds INTEGER NOT NULL CHECK (purge_after_seconds >= evidence_ttl_seconds),
    deletion_after_seconds INTEGER CHECK (deletion_after_seconds IS NULL OR deletion_after_seconds >= evidence_ttl_seconds),
    CHECK ((cache_status = 'HIT') = (cache_namespace IS NOT NULL AND cache_key IS NOT NULL AND cache_input_sha256 IS NOT NULL AND cache_output_sha256 IS NOT NULL AND cache_schema_version IS NOT NULL AND cache_model_version IS NOT NULL AND cache_prompt_version IS NOT NULL AND cache_policy_class IS NOT NULL)),
    CHECK (cache_status != 'HIT' OR (reservation_micro_usd = 0 AND cost_kind IN ('LOCAL_CACHE', 'FREE_METADATA'))),
    CHECK (cost_kind != 'PAID_CLOUD' OR price_card_id IS NOT NULL),
    UNIQUE (consent_token, display_order)
) STRICT;

CREATE TABLE planned_cost_component (
    id TEXT PRIMARY KEY,
    planned_call_id TEXT NOT NULL REFERENCES planned_provider_call(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    quantity_numerator INTEGER NOT NULL CHECK (quantity_numerator >= 0),
    quantity_denominator INTEGER NOT NULL CHECK (quantity_denominator > 0),
    unit TEXT NOT NULL,
    unit_price_micro_usd INTEGER NOT NULL CHECK (unit_price_micro_usd >= 0),
    maximum_micro_usd INTEGER NOT NULL CHECK (maximum_micro_usd >= 0),
    UNIQUE (planned_call_id, category)
) STRICT;

CREATE TABLE job (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES research_project(id) ON DELETE RESTRICT,
    run_scope_key TEXT NOT NULL,
    operation TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLING', 'CANCELLED', 'INTERRUPTED')),
    idempotency_key TEXT NOT NULL UNIQUE,
    protocol_version TEXT NOT NULL,
    payload_schema TEXT NOT NULL,
    input_sha256 TEXT NOT NULL CHECK (length(input_sha256) = 64),
    progress_percent INTEGER NOT NULL DEFAULT 0 CHECK (progress_percent BETWEEN 0 AND 100),
    phase TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    heartbeat_at_ms INTEGER,
    started_at_ms INTEGER,
    finished_at_ms INTEGER,
    cancellation_requested_at_ms INTEGER,
    sanitized_error TEXT,
    result_contract_json TEXT,
    created_at_ms INTEGER NOT NULL
) STRICT;

CREATE TABLE job_event (
    job_id TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    event_type TEXT NOT NULL,
    occurred_at_ms INTEGER NOT NULL,
    sanitized_payload_json TEXT NOT NULL,
    PRIMARY KEY (job_id, sequence)
) STRICT;

CREATE TABLE research_intent_revision (
    id TEXT PRIMARY KEY,
    parent_id TEXT REFERENCES research_intent_revision(id) ON DELETE RESTRICT,
    schema_version TEXT NOT NULL CHECK (schema_version = '2.0.0'),
    raw_user_query TEXT NOT NULL CHECK (length(raw_user_query) BETWEEN 1 AND 4000),
    request_contract_json TEXT NOT NULL CHECK (json_valid(request_contract_json)),
    canonical_contract_json TEXT NOT NULL,
    input_sha256 TEXT NOT NULL CHECK (length(input_sha256) = 64),
    created_at_ms INTEGER NOT NULL
) STRICT;

CREATE TABLE research_run (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE REFERENCES job(id) ON DELETE RESTRICT,
    intent_revision_id TEXT NOT NULL REFERENCES research_intent_revision(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLING', 'CANCELLED', 'INTERRUPTED')),
    freshness_cutoff_ms INTEGER NOT NULL,
    locale TEXT NOT NULL,
    warning_micro_usd INTEGER NOT NULL CHECK (warning_micro_usd >= 0),
    hard_micro_usd INTEGER NOT NULL CHECK (hard_micro_usd >= warning_micro_usd),
    summary TEXT,
    warnings_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(warnings_json)),
    canonical_result_json TEXT CHECK (canonical_result_json IS NULL OR json_valid(canonical_result_json)),
    evidence_sources_json TEXT CHECK (evidence_sources_json IS NULL OR json_valid(evidence_sources_json)),
    evidence_claims_json TEXT CHECK (evidence_claims_json IS NULL OR json_valid(evidence_claims_json)),
    created_at_ms INTEGER NOT NULL,
    finished_at_ms INTEGER
) STRICT;

CREATE TABLE provider_run (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES job(id) ON DELETE RESTRICT,
    planned_call_id TEXT NOT NULL UNIQUE REFERENCES planned_provider_call(id) ON DELETE RESTRICT,
    provider TEXT NOT NULL,
    configured_model TEXT,
    resolved_model TEXT,
    capability TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    provider_request_id TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('PENDING', 'SUCCESS', 'REFUSAL', 'INCOMPLETE', 'FAILED')),
    input_sha256 TEXT NOT NULL CHECK (length(input_sha256) = 64),
    output_sha256 TEXT CHECK (output_sha256 IS NULL OR length(output_sha256) = 64),
    retention_mode TEXT NOT NULL,
    data_use_mode TEXT NOT NULL,
    privacy_mode TEXT NOT NULL,
    requests INTEGER CHECK (requests IS NULL OR requests >= 0),
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    cached_input_tokens INTEGER CHECK (cached_input_tokens IS NULL OR cached_input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    reasoning_tokens INTEGER CHECK (reasoning_tokens IS NULL OR reasoning_tokens >= 0),
    tool_invocations INTEGER CHECK (tool_invocations IS NULL OR tool_invocations >= 0),
    repair_used INTEGER CHECK (repair_used IS NULL OR repair_used IN (0, 1)),
    tool_usage_json TEXT CHECK (tool_usage_json IS NULL OR json_valid(tool_usage_json)),
    provider_cost_ticks TEXT,
    started_at_ms INTEGER NOT NULL,
    finished_at_ms INTEGER
) STRICT;

CREATE TABLE provider_quota_entry (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES job(id) ON DELETE RESTRICT,
    planned_call_id TEXT NOT NULL REFERENCES planned_provider_call(id) ON DELETE RESTRICT,
    provider TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('RESERVED', 'ACTUAL', 'RELEASED', 'UNVERIFIED')),
    requests INTEGER NOT NULL CHECK (requests >= 0),
    tool_calls INTEGER NOT NULL CHECK (tool_calls >= 0),
    input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at_ms INTEGER NOT NULL
) STRICT;

CREATE TABLE cost_entry (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES job(id) ON DELETE RESTRICT,
    planned_call_id TEXT NOT NULL REFERENCES planned_provider_call(id) ON DELETE RESTRICT,
    provider_run_id TEXT REFERENCES provider_run(id) ON DELETE RESTRICT,
    price_card_id TEXT REFERENCES price_card(id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK (state IN ('RESERVED', 'ACTUAL', 'RELEASED', 'UNVERIFIED')),
    category TEXT NOT NULL,
    micro_usd INTEGER NOT NULL CHECK (micro_usd >= 0),
    provider_native_ticks TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at_ms INTEGER NOT NULL,
    reconciled_at_ms INTEGER,
    CHECK (state != 'ACTUAL' OR provider_run_id IS NOT NULL)
) STRICT;

CREATE TABLE evidence_source (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_record_id TEXT,
    source_type TEXT NOT NULL CHECK (source_type IN ('PRIMARY_RELEASE', 'OFFICIAL_CLIP', 'PLATFORM_SIGNAL', 'ARTICLE', 'METADATA')),
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL,
    author_or_channel TEXT,
    source_created_at_ms INTEGER,
    source_updated_at_ms INTEGER,
    page_published_at_ms INTEGER,
    retrieved_at_ms INTEGER NOT NULL,
    query TEXT NOT NULL,
    window_start_ms INTEGER,
    window_end_ms INTEGER,
    independence_group TEXT NOT NULL,
    policy_class TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    refresh_due_at_ms INTEGER,
    purge_due_at_ms INTEGER,
    expires_at_ms INTEGER,
    deletion_required_at_ms INTEGER,
    deleted_at_ms INTEGER,
    fetch_status TEXT NOT NULL,
    UNIQUE (provider, provider_record_id),
    UNIQUE (canonical_url, content_sha256)
) STRICT;

CREATE TABLE evidence_claim (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES evidence_source(id) ON DELETE RESTRICT,
    claim_kind TEXT NOT NULL CHECK (claim_kind IN ('WHY_NOW', 'VIEWER_DISCUSSION', 'EPISODE_IDENTITY', 'QUOTE', 'SCENE_CONTEXT', 'OFFICIAL_CLIP', 'CAST_IDENTITY')),
    excerpt_type TEXT NOT NULL CHECK (excerpt_type IN ('SHORT_QUOTE', 'PARAPHRASE', 'UNVERIFIED_QUOTE_LEAD')),
    text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 1000),
    episode_locator_json TEXT CHECK (episode_locator_json IS NULL OR json_valid(episode_locator_json)),
    quote_fact_json TEXT CHECK (quote_fact_json IS NULL OR json_valid(quote_fact_json)),
    why_now_event_json TEXT CHECK (why_now_event_json IS NULL OR json_valid(why_now_event_json)),
    scene_fact_json TEXT CHECK (scene_fact_json IS NULL OR json_valid(scene_fact_json)),
    cast_fact_json TEXT CHECK (cast_fact_json IS NULL OR json_valid(cast_fact_json)),
    event_or_release_at_ms INTEGER,
    verification TEXT NOT NULL CHECK (verification IN ('PRIMARY_VERIFIED', 'SECONDARY_CORROBORATED', 'LEAD_ONLY', 'STALE', 'RETRACTED')),
    confidence_ppm INTEGER NOT NULL CHECK (confidence_ppm BETWEEN 0 AND 1000000),
    supports_why_now INTEGER NOT NULL CHECK (supports_why_now IN (0, 1)),
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    canonical_contract_json TEXT NOT NULL CHECK (json_valid(canonical_contract_json)),
    CHECK (supports_why_now = 0 OR claim_kind NOT IN ('WHY_NOW', 'OFFICIAL_CLIP') OR (event_or_release_at_ms IS NOT NULL AND why_now_event_json IS NOT NULL)),
    CHECK (claim_kind != 'VIEWER_DISCUSSION' OR why_now_event_json IS NULL),
    CHECK (excerpt_type != 'SHORT_QUOTE' OR claim_kind = 'QUOTE'),
    CHECK (claim_kind != 'EPISODE_IDENTITY' OR (episode_locator_json IS NOT NULL AND quote_fact_json IS NULL)),
    CHECK (claim_kind != 'QUOTE' OR (quote_fact_json IS NOT NULL AND episode_locator_json IS NULL AND excerpt_type = 'SHORT_QUOTE')),
    CHECK (claim_kind != 'CAST_IDENTITY' OR (cast_fact_json IS NOT NULL AND episode_locator_json IS NULL AND quote_fact_json IS NULL AND why_now_event_json IS NULL AND scene_fact_json IS NULL)),
    CHECK (claim_kind = 'QUOTE' OR quote_fact_json IS NULL)
) STRICT;

CREATE VIRTUAL TABLE evidence_fts USING fts5(evidence_claim_id UNINDEXED, title, text, tokenize = 'unicode61');

CREATE TABLE opportunity (
    id TEXT PRIMARY KEY,
    research_run_id TEXT NOT NULL REFERENCES research_run(id) ON DELETE RESTRICT,
    footage_request_id TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank BETWEEN 1 AND 10),
    media_kind TEXT NOT NULL CHECK (media_kind IN ('TV_EPISODE', 'TV_SERIES', 'FILM', 'TRAILER', 'OFFICIAL_CLIP')),
    media_identity_json TEXT NOT NULL CHECK (json_valid(media_identity_json)),
    title TEXT NOT NULL,
    focus_json TEXT NOT NULL CHECK (json_valid(focus_json)),
    why_now TEXT NOT NULL,
    what_viewers_are_discussing TEXT NOT NULL,
    creative_hook TEXT NOT NULL,
    emotional_edit_direction TEXT NOT NULL,
    evidence_gate TEXT NOT NULL CHECK (evidence_gate IN ('PASSED', 'LOW_CONFIDENCE')),
    confidence_ppm INTEGER NOT NULL CHECK (confidence_ppm BETWEEN 0 AND 1000000),
    score_json TEXT NOT NULL CHECK (json_valid(score_json)),
    caveats_json TEXT NOT NULL CHECK (json_valid(caveats_json)),
    canonical_contract_json TEXT NOT NULL CHECK (json_valid(canonical_contract_json)),
    created_at_ms INTEGER NOT NULL,
    UNIQUE (research_run_id, rank),
    UNIQUE (footage_request_id)
) STRICT;

CREATE TABLE opportunity_evidence (
    opportunity_id TEXT NOT NULL REFERENCES opportunity(id) ON DELETE CASCADE,
    evidence_claim_id TEXT NOT NULL REFERENCES evidence_claim(id) ON DELETE RESTRICT,
    evidence_role TEXT NOT NULL CHECK (evidence_role IN ('PRIMARY_WHY_NOW', 'QUALITATIVE_SIGNAL', 'QUOTE_PROOF', 'CONTEXT')),
    independence_group TEXT NOT NULL,
    supports_why_now INTEGER NOT NULL CHECK (supports_why_now IN (0, 1)),
    PRIMARY KEY (opportunity_id, evidence_claim_id)
) STRICT;

CREATE TABLE footage_request (
    id TEXT PRIMARY KEY,
    opportunity_id TEXT NOT NULL UNIQUE REFERENCES opportunity(id) DEFERRABLE INITIALLY DEFERRED,
    schema_version TEXT NOT NULL CHECK (schema_version = '2.0.0'),
    summary TEXT NOT NULL,
    natural_best TEXT NOT NULL,
    natural_alternative TEXT,
    natural_minimum TEXT NOT NULL,
    natural_optional_improvement TEXT,
    smallest_useful_set_reason TEXT NOT NULL,
    search_queries_json TEXT NOT NULL CHECK (json_valid(search_queries_json)),
    warnings_json TEXT NOT NULL CHECK (json_valid(warnings_json)),
    canonical_contract_json TEXT NOT NULL CHECK (json_valid(canonical_contract_json)),
    created_at_ms INTEGER NOT NULL,
    FOREIGN KEY (id) REFERENCES opportunity(footage_request_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE footage_requirement (
    id TEXT PRIMARY KEY,
    footage_request_id TEXT NOT NULL REFERENCES footage_request(id) ON DELETE CASCADE,
    source_key TEXT NOT NULL,
    source_group TEXT NOT NULL CHECK (source_group IN ('REQUIRED', 'OPTIONAL', 'ALTERNATIVE')),
    priority INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 30),
    asset_kind TEXT NOT NULL CHECK (asset_kind IN ('EPISODE', 'OFFICIAL_TRAILER', 'OFFICIAL_CLIP', 'SCENE_PACK', 'INDIVIDUAL_SCENES')),
    show_or_title TEXT NOT NULL,
    season_number INTEGER CHECK (season_number IS NULL OR season_number BETWEEN 0 AND 999),
    episode_number INTEGER CHECK (episode_number IS NULL OR episode_number BETWEEN 1 AND 9999),
    episode_title TEXT,
    characters_json TEXT NOT NULL CHECK (json_valid(characters_json)),
    relationship_or_topic TEXT,
    scene_or_moment TEXT NOT NULL,
    purposes_json TEXT NOT NULL CHECK (json_valid(purposes_json)),
    verification_level TEXT NOT NULL CHECK (verification_level IN ('VERIFIED', 'STRONGLY_SUPPORTED', 'LIKELY_INFERRED', 'UNKNOWN')),
    source_quality_summary TEXT NOT NULL,
    supporting_claim_ids_json TEXT NOT NULL CHECK (json_valid(supporting_claim_ids_json)),
    quote_status TEXT CHECK (quote_status IS NULL OR quote_status IN ('VERIFIED', 'PARAPHRASE', 'UNVERIFIED_LEAD')),
    quote_text TEXT,
    quote_speaker TEXT,
    quote_likely_context TEXT,
    quote_claim_id TEXT REFERENCES evidence_claim(id) ON DELETE RESTRICT,
    why_it_matters_emotionally TEXT NOT NULL,
    acquisition_effort INTEGER NOT NULL CHECK (acquisition_effort BETWEEN 1 AND 5),
    search_queries_json TEXT NOT NULL CHECK (json_valid(search_queries_json)),
    replaces_required_source_keys_json TEXT NOT NULL CHECK (json_valid(replaces_required_source_keys_json)),
    in_minimum_useful_set INTEGER NOT NULL CHECK (in_minimum_useful_set IN (0, 1)),
    CHECK ((season_number IS NULL) = (episode_number IS NULL)),
    CHECK (asset_kind != 'EPISODE' OR season_number IS NOT NULL),
    CHECK (asset_kind = 'EPISODE' OR season_number IS NULL),
    CHECK (verification_level != 'UNKNOWN' OR (season_number IS NULL AND episode_title IS NULL)),
    CHECK (quote_status IS NULL OR quote_claim_id IS NOT NULL),
    CHECK (quote_status != 'VERIFIED' OR quote_speaker IS NOT NULL),
    CHECK (quote_status = 'VERIFIED' OR (quote_speaker IS NULL AND quote_likely_context IS NULL)),
    UNIQUE (footage_request_id, source_key),
    UNIQUE (id, footage_request_id),
    UNIQUE (footage_request_id, source_group, priority)
) STRICT;

CREATE TABLE footage_requirement_purpose (
    footage_requirement_id TEXT NOT NULL REFERENCES footage_requirement(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL CHECK (purpose IN ('INTRO', 'MONTAGE', 'PAYOFF', 'OPTIONAL_CALLBACK')),
    PRIMARY KEY (footage_requirement_id, purpose)
) STRICT;

CREATE TABLE footage_requirement_evidence (
    footage_requirement_id TEXT NOT NULL REFERENCES footage_requirement(id) ON DELETE CASCADE,
    evidence_claim_id TEXT NOT NULL REFERENCES evidence_claim(id) ON DELETE RESTRICT,
    PRIMARY KEY (footage_requirement_id, evidence_claim_id)
) STRICT;

CREATE TABLE footage_alternative_replacement (
    alternative_requirement_id TEXT NOT NULL,
    footage_request_id TEXT NOT NULL,
    required_source_key TEXT NOT NULL,
    PRIMARY KEY (alternative_requirement_id, required_source_key),
    FOREIGN KEY (alternative_requirement_id, footage_request_id) REFERENCES footage_requirement(id, footage_request_id) ON DELETE CASCADE,
    FOREIGN KEY (footage_request_id, required_source_key) REFERENCES footage_requirement(footage_request_id, source_key) ON DELETE CASCADE
) STRICT;

CREATE TRIGGER validate_footage_alternative_replacement
BEFORE INSERT ON footage_alternative_replacement
BEGIN
    SELECT CASE
        WHEN (SELECT source_group FROM footage_requirement WHERE id = NEW.alternative_requirement_id) != 'ALTERNATIVE'
        THEN RAISE(ABORT, 'replacement owner must be an ALTERNATIVE source')
    END;
    SELECT CASE
        WHEN (SELECT source_group FROM footage_requirement WHERE footage_request_id = NEW.footage_request_id AND source_key = NEW.required_source_key) != 'REQUIRED'
        THEN RAISE(ABORT, 'replacement target must be a REQUIRED source')
    END;
END;

CREATE TABLE intro_material_lead (
    id TEXT PRIMARY KEY,
    footage_request_id TEXT NOT NULL REFERENCES footage_request(id) ON DELETE CASCADE,
    source_key TEXT NOT NULL,
    display_order INTEGER NOT NULL CHECK (display_order >= 0),
    moment_description TEXT NOT NULL,
    quote_status TEXT CHECK (quote_status IS NULL OR quote_status IN ('VERIFIED', 'PARAPHRASE', 'UNVERIFIED_LEAD')),
    quote_text TEXT,
    quote_speaker TEXT,
    quote_likely_context TEXT,
    quote_claim_id TEXT REFERENCES evidence_claim(id) ON DELETE RESTRICT,
    why_it_might_lead_into_montage TEXT NOT NULL,
    verification_level TEXT NOT NULL CHECK (verification_level IN ('VERIFIED', 'STRONGLY_SUPPORTED', 'LIKELY_INFERRED', 'UNKNOWN')),
    supporting_claim_ids_json TEXT NOT NULL CHECK (json_valid(supporting_claim_ids_json)),
    CHECK (quote_status IS NULL OR quote_claim_id IS NOT NULL),
    CHECK (quote_status != 'VERIFIED' OR quote_speaker IS NOT NULL),
    CHECK (quote_status = 'VERIFIED' OR (quote_speaker IS NULL AND quote_likely_context IS NULL)),
    UNIQUE (footage_request_id, display_order),
    FOREIGN KEY (footage_request_id, source_key) REFERENCES footage_requirement(footage_request_id, source_key) ON DELETE CASCADE
) STRICT;

CREATE TABLE intro_material_evidence (
    intro_material_lead_id TEXT NOT NULL REFERENCES intro_material_lead(id) ON DELETE CASCADE,
    evidence_claim_id TEXT NOT NULL REFERENCES evidence_claim(id) ON DELETE RESTRICT,
    PRIMARY KEY (intro_material_lead_id, evidence_claim_id)
) STRICT;

CREATE TABLE footage_search_query (
    id TEXT PRIMARY KEY,
    footage_request_id TEXT NOT NULL REFERENCES footage_request(id) ON DELETE CASCADE,
    footage_requirement_id TEXT REFERENCES footage_requirement(id) ON DELETE CASCADE,
    display_order INTEGER NOT NULL CHECK (display_order >= 0),
    query TEXT NOT NULL CHECK (length(query) BETWEEN 1 AND 300),
    UNIQUE (footage_request_id, footage_requirement_id, display_order)
) STRICT;

CREATE TABLE external_link (
    handle TEXT PRIMARY KEY,
    evidence_source_id TEXT NOT NULL REFERENCES evidence_source(id) ON DELETE CASCADE,
    canonical_https_url TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
) STRICT;

CREATE INDEX idx_job_state ON job(state, created_at_ms);
CREATE INDEX idx_job_budget_scope ON job(project_id, run_scope_key);
CREATE INDEX idx_research_run_status ON research_run(status, created_at_ms);
CREATE INDEX idx_provider_run_job ON provider_run(job_id);
CREATE INDEX idx_evidence_expiry ON evidence_source(expires_at_ms, purge_due_at_ms);
CREATE INDEX idx_opportunity_run ON opportunity(research_run_id, rank);
CREATE INDEX idx_footage_requirement_request ON footage_requirement(footage_request_id, source_group, priority);
CREATE INDEX idx_cost_job_state ON cost_entry(job_id, state);
CREATE INDEX idx_cache_expiry ON cache_entry(state, expires_at_ms, purge_at_ms);
CREATE INDEX idx_cache_lease ON cache_entry(lease_expires_at_ms);
CREATE INDEX idx_cache_flight_lease ON cache_flight(lease_expires_at_ms);
CREATE INDEX idx_quota_provider ON provider_quota_entry(provider, created_at_ms);
CREATE UNIQUE INDEX uq_request_level_search_order
ON footage_search_query(footage_request_id, display_order)
WHERE footage_requirement_id IS NULL;
