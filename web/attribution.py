"""CC BY 4.0 credit required on every page and on GET /api."""

ATTRIBUTION_TEXT = (
    "Data: nflverse (nflverse-data), licensed CC BY 4.0. "
    "Changes: subset of columns, loaded into a database. "
    "Not affiliated with or endorsed by the NFL or nflverse. "
    "NFL data belong to their respective owners."
)

ROTOGURU_DK_CLASSIC_ATTRIBUTION = (
    "Historical DraftKings Classic salaries and points via RotoGuru (rotoguru1.com). "
    "Not affiliated with DraftKings."
)

ATTRIBUTION_LINKS = (
    {"label": "nflverse-data", "url": "https://github.com/nflverse/nflverse-data"},
    {"label": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
)


def attribution() -> dict:
    return {"text": ATTRIBUTION_TEXT, "links": [dict(link) for link in ATTRIBUTION_LINKS]}
