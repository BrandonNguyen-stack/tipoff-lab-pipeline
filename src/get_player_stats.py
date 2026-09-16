import pandas as pd
from nba_api.stats.endpoints import leaguedashplayerstats

TRICODE_FIX = {
    "GS": "GSW", "NO": "NOP", "NY": "NYK",
    "SA": "SAS", "UTAH": "UTA", "WSH": "WAS",
}

def normalize_tricode(code):
    return TRICODE_FIX.get(code, code)

def current_season():
    from datetime import date
    today = date.today()
    start_year = today.year if today.month >= 10 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[2:]}"

def get_player_stats(season=None):
    if season is None:
        season = current_season()
    print("Fetching player stats from NBA API...")
    df = leaguedashplayerstats.LeagueDashPlayerStats(
        season=season,
        per_mode_detailed="PerGame"
    ).get_data_frames()[0]

    df["TEAM_ABBREVIATION"] = df["TEAM_ABBREVIATION"].apply(normalize_tricode)

    # Build per-team star data
    team_stats = {}
    for team, group in df.groupby("TEAM_ABBREVIATION"):
        stars = group[group["PTS"] >= 14][["PLAYER_NAME", "PTS"]].sort_values("PTS", ascending=False)
        star_list = [(row["PLAYER_NAME"], row["PTS"]) for _, row in stars.iterrows()]
        star_power = group["PTS"].nlargest(3).sum()
        top_avg = group["PTS"].max() if len(group) > 0 else 0
        team_stats[team] = {
            "star_power": round(float(star_power), 1),
            "top_star_avg": round(float(top_avg), 1),
            "star_names": star_list,
        }

    print(f"Loaded player stats for {len(team_stats)} teams.")
    return team_stats

if __name__ == "__main__":
    stats = get_player_stats()
    for team in ["OKC", "SAS", "NYK", "CLE"]:
        print(f"{team}: {stats.get(team)}")
