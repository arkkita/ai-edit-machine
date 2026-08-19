-- TVmaze and other metadata sources legitimately use calendar years as
-- numeric season identifiers for continuing/daily series. Rebuild only the
-- footage-requirement subtree so verified values such as 2026 remain exact.

CREATE TABLE footage_requirement_wide (
    id TEXT PRIMARY KEY,
    footage_request_id TEXT NOT NULL REFERENCES footage_request(id) ON DELETE CASCADE,
    source_key TEXT NOT NULL,
    source_group TEXT NOT NULL CHECK (source_group IN ('REQUIRED', 'OPTIONAL', 'ALTERNATIVE')),
    priority INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 30),
    asset_kind TEXT NOT NULL CHECK (asset_kind IN ('EPISODE', 'OFFICIAL_TRAILER', 'OFFICIAL_CLIP', 'SCENE_PACK', 'INDIVIDUAL_SCENES')),
    show_or_title TEXT NOT NULL,
    season_number INTEGER CHECK (season_number IS NULL OR season_number BETWEEN 0 AND 9999),
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

CREATE TABLE footage_requirement_purpose_wide (
    footage_requirement_id TEXT NOT NULL REFERENCES footage_requirement_wide(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL CHECK (purpose IN ('INTRO', 'MONTAGE', 'PAYOFF', 'OPTIONAL_CALLBACK')),
    PRIMARY KEY (footage_requirement_id, purpose)
) STRICT;

CREATE TABLE footage_requirement_evidence_wide (
    footage_requirement_id TEXT NOT NULL REFERENCES footage_requirement_wide(id) ON DELETE CASCADE,
    evidence_claim_id TEXT NOT NULL REFERENCES evidence_claim(id) ON DELETE RESTRICT,
    PRIMARY KEY (footage_requirement_id, evidence_claim_id)
) STRICT;

CREATE TABLE footage_alternative_replacement_wide (
    alternative_requirement_id TEXT NOT NULL,
    footage_request_id TEXT NOT NULL,
    required_source_key TEXT NOT NULL,
    PRIMARY KEY (alternative_requirement_id, required_source_key),
    FOREIGN KEY (alternative_requirement_id, footage_request_id) REFERENCES footage_requirement_wide(id, footage_request_id) ON DELETE CASCADE,
    FOREIGN KEY (footage_request_id, required_source_key) REFERENCES footage_requirement_wide(footage_request_id, source_key) ON DELETE CASCADE
) STRICT;

CREATE TABLE intro_material_lead_wide (
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
    FOREIGN KEY (footage_request_id, source_key) REFERENCES footage_requirement_wide(footage_request_id, source_key) ON DELETE CASCADE
) STRICT;

CREATE TABLE intro_material_evidence_wide (
    intro_material_lead_id TEXT NOT NULL REFERENCES intro_material_lead_wide(id) ON DELETE CASCADE,
    evidence_claim_id TEXT NOT NULL REFERENCES evidence_claim(id) ON DELETE RESTRICT,
    PRIMARY KEY (intro_material_lead_id, evidence_claim_id)
) STRICT;

CREATE TABLE footage_search_query_wide (
    id TEXT PRIMARY KEY,
    footage_request_id TEXT NOT NULL REFERENCES footage_request(id) ON DELETE CASCADE,
    footage_requirement_id TEXT REFERENCES footage_requirement_wide(id) ON DELETE CASCADE,
    display_order INTEGER NOT NULL CHECK (display_order >= 0),
    query TEXT NOT NULL CHECK (length(query) BETWEEN 1 AND 300),
    UNIQUE (footage_request_id, footage_requirement_id, display_order)
) STRICT;

INSERT INTO footage_requirement_wide
SELECT * FROM footage_requirement;
INSERT INTO footage_requirement_purpose_wide
SELECT * FROM footage_requirement_purpose;
INSERT INTO footage_requirement_evidence_wide
SELECT * FROM footage_requirement_evidence;
INSERT INTO footage_alternative_replacement_wide
SELECT * FROM footage_alternative_replacement;
INSERT INTO intro_material_lead_wide
SELECT * FROM intro_material_lead;
INSERT INTO intro_material_evidence_wide
SELECT * FROM intro_material_evidence;
INSERT INTO footage_search_query_wide
SELECT * FROM footage_search_query;

DROP TABLE intro_material_evidence;
DROP TABLE footage_search_query;
DROP TABLE intro_material_lead;
DROP TABLE footage_alternative_replacement;
DROP TABLE footage_requirement_evidence;
DROP TABLE footage_requirement_purpose;
DROP TABLE footage_requirement;

ALTER TABLE footage_requirement_wide RENAME TO footage_requirement;
ALTER TABLE footage_requirement_purpose_wide RENAME TO footage_requirement_purpose;
ALTER TABLE footage_requirement_evidence_wide RENAME TO footage_requirement_evidence;
ALTER TABLE footage_alternative_replacement_wide RENAME TO footage_alternative_replacement;
ALTER TABLE intro_material_lead_wide RENAME TO intro_material_lead;
ALTER TABLE intro_material_evidence_wide RENAME TO intro_material_evidence;
ALTER TABLE footage_search_query_wide RENAME TO footage_search_query;

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

CREATE INDEX idx_footage_requirement_request
ON footage_requirement(footage_request_id, source_group, priority);

CREATE UNIQUE INDEX uq_request_level_search_order
ON footage_search_query(footage_request_id, display_order)
WHERE footage_requirement_id IS NULL;
