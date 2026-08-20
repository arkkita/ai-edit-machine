CREATE TABLE recommendation_feedback (
    id TEXT PRIMARY KEY,
    research_run_id TEXT NOT NULL REFERENCES research_run(id) ON DELETE RESTRICT,
    opportunity_id TEXT NOT NULL REFERENCES opportunity(id) ON DELETE RESTRICT,
    concept_id TEXT,
    rating TEXT NOT NULL CHECK (rating IN (
        'GREAT_RECOMMENDATION',
        'RELEVANT_BUT_BORING',
        'WRONG_AUDIENCE',
        'NOT_ACTUALLY_TRENDING',
        'WEAK_EVIDENCE',
        'FOOTAGE_REQUEST_TOO_VAGUE',
        'HIDE_THIS_TYPE',
        'GENERATE_ANOTHER_IDEA',
        'MORE_LIKE_THIS',
        'TOO_GENERIC',
        'DONT_CARE_ABOUT_THIS_ANGLE'
    )),
    created_at_ms INTEGER NOT NULL,
    CHECK (concept_id IS NULL OR length(concept_id) = 36)
) STRICT;

CREATE INDEX idx_recommendation_feedback_run
ON recommendation_feedback(research_run_id, opportunity_id, created_at_ms);
