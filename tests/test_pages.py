"""AT19-AT23: server-rendered pages."""

import re
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from sqlalchemy import text

ADR_TEXT = (
    "Data: nflverse (nflverse-data), licensed CC BY 4.0. "
    "Changes: subset of columns, loaded into a database. "
    "Not affiliated with or endorsed by the NFL or nflverse. "
    "NFL data belong to their respective owners."
)

FORM_FIELDS = {
    "/teams": {"conf", "division"},
    "/players": {"q", "position", "team", "status"},
    "/games": {"season", "week", "season_type", "team"},
    "/stats": {"season", "week", "season_type", "team", "position", "player"},
    "/load-runs": {"dataset", "status", "season"},
}


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._section = None
        self._in_cell = False
        self._href = None
        self._buf: list[str] = []
        self.headers = []
        self.rows = []
        self._row: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"thead", "tbody"}:
            self._section = tag
        elif tag == "tr" and self._section:
            self._row = []
        elif tag == "th" and self._section == "thead":
            self._in_cell = True
            self._href = None
            self._buf = []
        elif tag == "td" and self._section == "tbody":
            self._in_cell = True
            self._buf = []
        elif tag == "a" and self._in_cell:
            self._href = attrs.get("href")

    def handle_endtag(self, tag):
        if tag in {"thead", "tbody"}:
            self._section = None
        elif tag == "tr" and self._section == "tbody":
            self.rows.append(self._row)
        elif tag == "th" and self._in_cell and self._section == "thead":
            self.headers.append({"label": "".join(self._buf).strip(), "href": self._href})
            self._in_cell = False
        elif tag == "td" and self._in_cell:
            self._row.append("".join(self._buf).strip())
            self._in_cell = False

    def handle_data(self, data):
        if self._in_cell:
            self._buf.append(data)


def _inputs(html: str) -> set[str]:
    return set(re.findall(r'<input[^>]*name="([^"]+)"', html))


def _column(html: str, label: str) -> list[str]:
    parser = TableParser()
    parser.feed(html)
    index = next(i for i, header in enumerate(parser.headers) if header["label"] == label)
    return [row[index] for row in parser.rows]


def _header_href(html: str, label: str) -> str:
    parser = TableParser()
    parser.feed(html)
    header = next(item for item in parser.headers if item["label"] == label)
    assert header["href"]
    return unescape(header["href"])


def _latest_refresh_label(engine) -> str:
    with engine.connect() as conn:
        finished = conn.execute(
            text(
                """
                SELECT finished_at FROM load_runs
                WHERE status = 'succeeded' AND finished_at IS NOT NULL
                ORDER BY finished_at DESC, id DESC
                LIMIT 1
                """
            )
        ).scalar_one()
    return finished.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S ET")


def test_empty_table_has_zero_range_and_no_refresh(client):
    response = client.get("/teams")
    assert response.status_code == 200
    assert "rows 0-0 of 0" in response.text
    assert ">Next</a>" not in response.text
    assert ">Previous</a>" not in response.text
    assert "Last refresh: none" in response.text


def _insert_named_players(engine, count):
    rows = [
        {"gsis_id": f"99-{index:07d}", "display_name": f"Fictional Player {index:03d}"}
        for index in range(1, count + 1)
    ]
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO players (gsis_id, display_name, is_stub, loaded_at)
                VALUES (:gsis_id, :display_name, true, CURRENT_TIMESTAMP)
                """
            ),
            rows,
        )


def _href_named(html: str, label: str) -> str:
    match = re.search(rf'href="([^"]+)">{label}</a>', html)
    assert match, html
    return unescape(match.group(1))


def test_paging_links_keep_filters_and_stop_on_the_last_page(client, engine):
    _insert_named_players(engine, 100)
    first = client.get("/players", params={"limit": 10})
    assert first.status_code == 200
    assert "rows 1-10 of 100" in first.text
    assert ">Previous</a>" not in first.text
    nxt = _href_named(first.text, "Next")
    query = parse_qs(urlparse(nxt).query)
    assert query["limit"] == ["10"]
    assert query["offset"] == ["10"]

    last = client.get("/players", params={"limit": 50, "offset": 50})
    assert "rows 51-100 of 100" in last.text
    assert ">Next</a>" not in last.text
    prev = _href_named(last.text, "Previous")
    assert "offset" not in parse_qs(urlparse(prev).query)
    assert "rows 1-50 of 100" in client.get(prev).text

    one = client.get("/players", params={"limit": 1})
    assert parse_qs(urlparse(_href_named(one.text, "Next")).query)["offset"] == ["1"]
    offset_one = client.get("/players", params={"limit": 1, "offset": 1})
    assert ">Previous</a>" in offset_one.text


def test_at19_each_table_page_renders(client, loaded):
    for path, fields in FORM_FIELDS.items():
        response = client.get(path)
        assert response.status_code == 200, path
        assert "text/html" in response.headers["content-type"]
        html = response.text
        assert "<table" in html
        assert "<form" in html
        assert 'method="get"' in html
        assert fields <= _inputs(html)
        assert "<img" not in html.lower()


def test_home_links_each_page_and_dataset_refresh(client, loaded):
    response = client.get("/")
    assert response.status_code == 200
    for href in ("/teams", "/players", "/games", "/stats", "/load-runs"):
        assert f'href="{href}"' in response.text
    for dataset in ("teams", "players", "games", "player_week_stats"):
        assert dataset in response.text
    assert "Last refresh per dataset" in response.text


def _seed_cin_week(engine):
    players = [
        {"gsis_id": f"99-{index:07d}", "display_name": f"Fictional Player {index:03d}"}
        for index in range(1, 111)
    ]
    stats = [
        {"gsis_id": f"99-{index:07d}", "yards": 500 if index == 1 else index}
        for index in range(1, 111)
    ]
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO players (gsis_id, display_name, position, is_stub, loaded_at)
                VALUES (:gsis_id, :display_name, 'WR', true, CURRENT_TIMESTAMP)
                """
            ),
            players,
        )
        conn.execute(
            text(
                """
                INSERT INTO player_week_stats (
                    gsis_id, season, week, season_type, game_id, team, opponent_team, position,
                    completions, attempts, passing_yards, passing_tds, passing_interceptions,
                    sacks_suffered, sack_fumbles_lost, passing_2pt_conversions,
                    carries, rushing_yards, rushing_tds, rushing_fumbles_lost,
                    rushing_2pt_conversions, receptions, targets, receiving_yards, receiving_tds,
                    receiving_fumbles_lost, receiving_2pt_conversions, special_teams_tds,
                    fantasy_points, fantasy_points_ppr, loaded_at
                ) VALUES (
                    :gsis_id, 2024, 10, 'REG', '2024_10_CIN_BAL', 'CIN', 'BAL', 'WR',
                    0, 0, 0, 0, 0,
                    0, 0, 0,
                    0, 0, 0, 0,
                    0, 0, 0, :yards, 0,
                    0, 0, 0,
                    0.50, 0.50, CURRENT_TIMESTAMP
                )
                """
            ),
            stats,
        )


def test_at20_filters_sort_and_paging(client, loaded, engine):
    _seed_cin_week(engine)
    page = client.get("/stats", params={"season": "2024", "week": "10", "team": "CIN"})
    assert page.status_code == 200
    assert "Ja'Marr Chase" in unescape(page.text)
    assert _column(page.text, "player_display_name")[0] == "Ja'Marr Chase"

    href = _header_href(page.text, "receiving_yards")
    parsed = parse_qs(urlparse(href).query)
    assert parsed["sort"] == ["receiving_yards"]
    assert parsed["order"] == ["desc"]
    assert parsed["season"] == ["2024"]
    assert parsed["week"] == ["10"]
    assert parsed["team"] == ["CIN"]
    ordered = client.get(href)
    assert ordered.status_code == 200
    names = _column(ordered.text, "player_display_name")
    yards = [int(value) for value in _column(ordered.text, "receiving_yards")]
    assert names[0] == "Fictional Player 001"
    assert yards == sorted(yards, reverse=True)
    flipped = parse_qs(urlparse(_header_href(ordered.text, "receiving_yards")).query)
    assert flipped["order"] == ["asc"]

    match = re.search(r'href="([^"]+)">Next</a>', page.text)
    assert match
    next_url = unescape(match.group(1))
    query = parse_qs(urlparse(next_url).query)
    assert query["season"] == ["2024"]
    assert query["week"] == ["10"]
    assert query["team"] == ["CIN"]
    assert query["offset"] == ["50"]
    nxt = client.get(next_url)
    assert nxt.status_code == 200
    assert "rows 51-100 of " in nxt.text
    assert len(_column(nxt.text, "gsis_id")) == 50


def test_at21_bad_page_params(client, loaded):
    response = client.get("/games", params={"week": "abc"})
    assert response.status_code == 400
    assert "week must be an integer from 1 to 22" in response.text
    assert "<form" in response.text
    assert ADR_TEXT in response.text
    assert "Traceback" not in response.text


def test_at22_attribution_on_every_page(client, loaded, engine):
    expected = _latest_refresh_label(engine)
    assert expected.endswith(" ET")
    assert datetime.strptime(expected, "%Y-%m-%d %H:%M:%S ET")
    paths = ["/", "/teams", "/players", "/games", "/stats", "/load-runs", "/games?week=abc"]
    for path in paths:
        response = client.get(path)
        assert ADR_TEXT in response.text, path
        assert 'href="https://github.com/nflverse/nflverse-data"' in response.text
        assert 'href="https://creativecommons.org/licenses/by/4.0/"' in response.text
        assert f"Last refresh: {expected}" in response.text, path


def test_at23_no_external_images(client, loaded):
    paths = ["/", "/teams", "/players", "/games", "/stats", "/load-runs", "/games?week=abc"]
    for path in paths:
        html = client.get(path).text.lower()
        assert "<img" not in html, path
        assert "url(http" not in html, path
        assert "url(//" not in html, path
