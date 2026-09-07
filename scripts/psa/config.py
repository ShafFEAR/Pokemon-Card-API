import tempfile
from pathlib import Path

# This copy runs inside a fresh, ephemeral GitHub Actions workspace each time
# (see .github/workflows/refresh-psa-data.yml), so the working db is scratch
# space, not persisted - only data/psa/*.json (written by publish_psa_data.py)
# is ever committed. Full price *history* therefore lives in git commit
# history (one snapshot per scheduled run), not in a queryable local db like
# the source project (PSAPokemonTracker) keeps for local use.
DB_PATH = Path(tempfile.gettempdir()) / "psa_publish_scratch.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

MIRROR_BASE_URL = "https://shaffear.github.io/Pokemon-Card-API/data"

PSA_BASE_URL = "https://www.psacard.com"
PSA_CATEGORY_URL = f"{PSA_BASE_URL}/priceguide/non-sports-tcg-card-values/7"

# A real browser UA is required - PSA returns 403 to generic/library user agents.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# PSA's robots.txt specifies "Crawl-delay: 1" for the price guide paths.
PSA_REQUEST_DELAY_SECONDS = 1.0
