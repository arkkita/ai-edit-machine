"""Immutable development-only contract for the single M1 provider probe."""

DEBUG_MODE = "M1_PROVIDER_ONE_SHOT"
DEBUG_PROVIDER = "openai"
DEBUG_MODEL = "gpt-5.6-luna"
DEBUG_ENDPOINT = "https://api.openai.com/v1/responses"
DEBUG_PROMPT = "a good show for girls thatll get views on tiktok"

# One required hosted search, a deliberately tiny output, and a conservative
# aggregate provider-input allowance fit below the independent $0.05 run cap
# under the reviewed 2026-08-19 immutable price card.
DEBUG_MAX_REQUESTS = 8
DEBUG_MAX_TOOL_CALLS = 1
DEBUG_MAX_INPUT_TOKENS = 198_000
DEBUG_MAX_OUTPUT_TOKENS = 300
DEBUG_RESERVED_MICRO_USD = 49_960
DEBUG_HARD_CAP_MICRO_USD = 50_000

# This fixed, already-normalized public TVmaze record keeps the paid request to
# one immutable current title.  It is a development fixture, not a claim that
# the application watched the episode or that any scene occurs in it.
DEBUG_SEED_SHOW = "The Real Housewives: Ultimate Girls Trip"
DEBUG_SEED_SEASON = 5
DEBUG_SEED_EPISODE = 2
DEBUG_SEED_EPISODE_TITLE = "Leather You Like It or Not"
DEBUG_SEED_EVENT_AT = "2026-08-17T01:00:00Z"
DEBUG_SEED_URL = (
    "https://www.tvmaze.com/episodes/3686306/"
    "the-real-housewives-ultimate-girls-trip-5x02-leather-you-like-it-or-not"
)
DEBUG_SEED_PROVIDER_RECORD_ID = "3686306"
