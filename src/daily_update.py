import pandas as pd
import numpy as np
import pickle
import sys
import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from supabase import create_client
from dotenv import load_dotenv

sys.path.insert(0, "src")
from predict import predict_today
from get_injuries import get_injuries
from get_standings import get_standings
from get_schedule import get_schedule_stats
from get_player_stats import get_player_stats
from cache_manager import save_cache, load_cache

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"

ESPN_TRICODE_FIX = {
    "GS": "GSW",
    "NO": "NOP",
    "NY": "NYK",
    "SA": "SAS",
    "UTAH": "UTA",
    "WSH": "WAS",
}

FULL_NAME_TO_TRICODE = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP", "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}


def normalize_tricode(code):
    return ESPN_TRICODE_FIX.get(code, code)


def get_odds():
    """Fetch spread and total for today's NBA games from The Odds API."""
    r = requests.get(ODDS_API_URL, params={
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "spreads,totals",
        "oddsFormat": "american",
    }, timeout=10)
    r.raise_for_status()
    print(f"Odds API requests remaining: {r.headers.get('x-requests-remaining')}")

    odds_map = {}
    for game in r.json():
        home = FULL_NAME_TO_TRICODE.get(game["home_team"])
        away = FULL_NAME_TO_TRICODE.get(game["away_team"])
        if not home or not away:
            print(f"Unknown team name: {game['home_team']} or {game['away_team']}")
            continue

        spread = None
        total = None

        for bm in game.get("bookmakers", []):
            markets = {m["key"]: m["outcomes"] for m in bm["markets"]}
            if "spreads" in markets and "totals" in markets:
                for outcome in markets["spreads"]:
                    if FULL_NAME_TO_TRICODE.get(outcome["name"]) == home:
                        spread = outcome["point"]
                for outcome in markets["totals"]:
                    if outcome["name"] == "Over":
                        total = outcome["point"]
                if spread is not None and total is not None:
                    break

        odds_map[(home, away)] = (spread, total)
        print(f"  Odds: {away} @ {home} — spread: {spread}, total: {total}")

    return odds_map


def get_todays_games(game_date=None):
    """Fetch today's NBA games from ESPN's scoreboard API."""
    params = {}
    if game_date:
        params["dates"] = game_date.replace("-", "")

    r = requests.get(ESPN_SCOREBOARD_URL, params=params, timeout=10)
    r.raise_for_status()

    matchups = []
    for event in r.json().get("events", []):
        comp = event["competitions"][0]
        home = None
        away = None
        for team in comp["competitors"]:
            tri = normalize_tricode(team["team"]["abbreviation"])
            if team["homeAway"] == "home":
                home = tri
            else:
                away = tri
        if home and away:
            playoff_game_num = 0
            series = comp.get("series")
            if series and series.get("type") == "playoff":
                wins = [c.get("wins", 0) for c in comp.get("competitors", [])]
                playoff_game_num = sum(wins) + 1
            matchups.append((home, away, playoff_game_num))

    print(f"Found {len(matchups)} games: {matchups}")
    return matchups


def run_daily_update(game_date=None):
    if game_date is None:
        game_date = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    print(f"Running daily update for {game_date}...")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("Loading model and data...")
    with open("data/model.pkl", "rb") as f:
        model = pickle.load(f)
    games = pd.read_parquet("data/games.parquet")
    games["date"] = pd.to_datetime(games["date"])

    matchups_raw = get_todays_games(game_date)
    if not matchups_raw:
        print("No games today, exiting.")
        return

    odds_key = f"odds_{game_date}"
    cached_odds = load_cache(odds_key)
    if cached_odds is not None:
        odds_map = {tuple(k.split("@")): tuple(v) for k, v in cached_odds.items()}
    else:
        print("Fetching fresh odds from API...")
        try:
            odds_map = get_odds()
        except Exception as e:
            print(f"Warning: odds fetch failed, continuing without lines: {e}")
            odds_map = {}
        save_cache(odds_key, {f"{h}@{a}": list(v) for (h, a), v in odds_map.items()})

    print("Fetching standings...")
    standings = load_cache("standings")
    if standings is None:
        try:
            standings = get_standings()
            save_cache("standings", standings)
        except Exception as e:
            print(f"Warning: standings fetch failed, continuing without them: {e}")
            standings = {}

    print("Fetching player stats...")
    player_stats = load_cache("player_stats")
    if not player_stats:
        try:
            player_stats = get_player_stats()
        except Exception as e:
            print(f"Warning: player stats fetch failed, continuing without them: {e}")
            player_stats = {}
        if player_stats:
            save_cache("player_stats", player_stats)

    print("Fetching injury report...")
    team_injuries = get_injuries()

    matchups = []
    for home, away, playoff_game_num in matchups_raw:
        spread, total = odds_map.get((home, away), (None, None))
        matchups.append((home, away, spread, total, playoff_game_num))

    results = predict_today(game_date, matchups, games, model, team_injuries=team_injuries, standings=standings, player_stats=player_stats)
    if not results:
        print("No predictions generated.")
        return

    print(f"\nGenerated {len(results)} predictions:")
    for r in results:
        print(f"  {r['watchability']:.1f}/10 - {r['away_team']} @ {r['home_team']}: {r['reasons']}")

    rows = []
    for r in results:
        spread, total = odds_map.get((r["home_team"], r["away_team"]), (None, None))
        rows.append({
            "game_date": game_date,
            "home_team": r["home_team"],
            "away_team": r["away_team"],
            "watchability": r["watchability"],
            "reasons": r["reasons"],
            "spread": spread,
            "total": total,
            "badges": r.get("badges", []),
            "injury_note": ", ".join(
                team_injuries.get(r["home_team"], {}).get("out", [])[:2] +
                team_injuries.get(r["away_team"], {}).get("out", [])[:2]
            ),
        })
    supabase.table("predictions").delete().eq("game_date", str(game_date)).execute()
    supabase.table("predictions").insert(rows).execute()
    print(f"Saved {len(rows)} predictions to Supabase.")


if __name__ == "__main__":
    run_daily_update()