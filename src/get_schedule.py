import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from cache_manager import load_cache, save_cache

ESPN_TEAM_SCHEDULE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/schedule"

TRICODE_TO_ESPN_ID = {
    "ATL": "1", "BOS": "2", "BKN": "17", "CHA": "30", "CHI": "4",
    "CLE": "5", "DAL": "6", "DEN": "7", "DET": "8", "GSW": "9",
    "HOU": "10", "IND": "11", "LAC": "12", "LAL": "13", "MEM": "29",
    "MIA": "14", "MIL": "15", "MIN": "16", "NOP": "3", "NYK": "18",
    "OKC": "25", "ORL": "19", "PHI": "20", "PHX": "21", "POR": "22",
    "SAC": "23", "SAS": "24", "TOR": "28", "UTA": "26", "WAS": "27",
}

ESPN_TRICODE_FIX = {
    "GS": "GSW", "NO": "NOP", "NY": "NYK",
    "SA": "SAS", "UTAH": "UTA", "WSH": "WAS",
}

def normalize_tricode(code):
    return ESPN_TRICODE_FIX.get(code, code)

def _event_date_to_local(date_str):
    return datetime.fromisoformat(date_str.replace("Z", "+00:00")).astimezone(ZoneInfo("America/Los_Angeles")).date()

def get_all_schedules():
    cached = load_cache("schedules", max_age_hours=6)
    if cached is not None:
        return cached
    schedules = {}
    for tricode, team_id in TRICODE_TO_ESPN_ID.items():
        try:
            url = ESPN_TEAM_SCHEDULE_URL.format(team_id=team_id)
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            events = r.json().get("events", [])
            dates = []
            for event in events:
                dates.append(event["date"])
            schedules[tricode] = dates
        except Exception as e:
            print(f"Schedule fetch failed for {tricode}: {e}")
            schedules[tricode] = []
    save_cache("schedules", schedules)
    return schedules

def get_team_recent_games(tricode, game_date_str):
    team_id = TRICODE_TO_ESPN_ID.get(tricode)
    if not team_id:
        return []
    try:
        url = ESPN_TEAM_SCHEDULE_URL.format(team_id=team_id)
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        events = r.json().get("events", [])
        game_date = datetime.strptime(game_date_str, "%Y-%m-%d").date()
        past_games = []
        for event in events:
            event_date = _event_date_to_local(event["date"])
            if event_date < game_date:
                past_games.append(event_date)
        past_games.sort(reverse=True)
        return past_games
    except Exception as e:
        print(f"Schedule fetch failed for {tricode}: {e}")
        return []

def get_rest_stats(tricode, game_date_str, schedules=None):
    game_date = datetime.strptime(game_date_str, "%Y-%m-%d").date()

    if schedules is not None and tricode in schedules:
        past_games = sorted(
            (d for d in (_event_date_to_local(e) for e in schedules[tricode]) if d < game_date),
            reverse=True,
        )
    else:
        past_games = get_team_recent_games(tricode, game_date_str)

    if not past_games:
        return {"rest_days": 7, "b2b": False, "3in4": False}

    last_game = past_games[0]
    rest_days = (game_date - last_game).days

    b2b = rest_days <= 1

    # 3-in-4: played 2+ games in the last 3 days before today
    recent = [g for g in past_games if (game_date - g).days <= 3]
    three_in_four = len(recent) >= 2

    return {
        "rest_days": min(rest_days, 7),
        "b2b": b2b,
        "3in4": three_in_four,
    }

def get_schedule_stats(home_team, away_team, game_date_str):
    schedules = get_all_schedules()
    home = get_rest_stats(home_team, game_date_str, schedules)
    away = get_rest_stats(away_team, game_date_str, schedules)
    print(f"  {home_team} rest: {home['rest_days']}d, b2b: {home['b2b']}, 3in4: {home['3in4']}")
    print(f"  {away_team} rest: {away['rest_days']}d, b2b: {away['b2b']}, 3in4: {away['3in4']}")
    return home, away

if __name__ == "__main__":
    home, away = get_schedule_stats("SAS", "OKC", "2026-05-22")
    print("SAS:", home)
    print("OKC:", away)
