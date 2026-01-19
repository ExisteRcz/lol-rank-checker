from flask import Flask, render_template, request, jsonify
import requests
from collections import defaultdict
import sqlite3
import json
import time
import os
import re

app = Flask(__name__)

API_KEY = os.environ.get("RIOT_API_KEY", "RGAPI-a68d3734-f59b-4a4a-b688-fb4ddce0c125")
CHAMPIONS = {}
DDRAGON_VERSION = "14.24.1"
DB_PATH = os.environ.get("DB_PATH", "players.db")

CURRENT_SEASON = "S2025 S1"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS players (
            id TEXT PRIMARY KEY,
            game_name TEXT,
            tag_line TEXT,
            region TEXT,
            data TEXT,
            updated_at INTEGER
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS season_history_cache (
            id TEXT PRIMARY KEY,
            data TEXT,
            updated_at INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def get_cached_player(game_name, tag_line, region):
    player_id = f"{game_name.lower()}#{tag_line.lower()}#{region}"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT data, updated_at FROM players WHERE id = ?", (player_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0]), row[1]
    return None, None

def save_player(game_name, tag_line, region, data):
    player_id = f"{game_name.lower()}#{tag_line.lower()}#{region}"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO players (id, game_name, tag_line, region, data, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (player_id, game_name, tag_line, region, json.dumps(data), int(time.time())))
    conn.commit()
    conn.close()

def get_cached_season_history(game_name, tag_line, region):
    """Get cached season history"""
    player_id = f"{game_name.lower()}#{tag_line.lower()}#{region}"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT data, updated_at FROM season_history_cache WHERE id = ?", (player_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0]), row[1]
    return None, None

def save_season_history_cache(game_name, tag_line, region, data):
    """Cache season history"""
    player_id = f"{game_name.lower()}#{tag_line.lower()}#{region}"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO season_history_cache (id, data, updated_at)
        VALUES (?, ?, ?)
    ''', (player_id, json.dumps(data), int(time.time())))
    conn.commit()
    conn.close()

def season_sort_key(season):
    """Convert season string to sortable tuple (year, split)"""
    # S2025 -> (2025, 0), S14 S3 -> (14, 3), S7 -> (7, 0)
    match = re.match(r'S(\d+)(?:\s*S(\d))?', season)
    if match:
        year = int(match.group(1))
        split = int(match.group(2)) if match.group(2) else 0
        return (year, split)
    return (0, 0)

def scrape_season_history(game_name, tag_line, region):
    """Scrape season history from leagueofgraphs.com"""
    log_regions = {
        "eun1": "eune",
        "euw1": "euw",
        "na1": "na",
        "kr": "kr",
        "br1": "br",
        "tr1": "tr",
        "ru": "ru",
        "la1": "lan",
        "la2": "las",
    }
    log_region = log_regions.get(region, "eune")

    summoner_slug = f"{game_name}-{tag_line}"
    url = f"https://www.leagueofgraphs.com/summoner/{log_region}/{summoner_slug}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return {}

        content = response.text

        # Pattern: "Season X. At the end of the season, this player was Tier Division"
        pattern = r'Season\s*(\d+)(?:\s*\(([^)]+)\))?[^<]*?this player was\s*(Iron|Bronze|Silver|Gold|Platinum|Emerald|Diamond|Master|Grandmaster|Challenger)\s*(I{1,3}|IV)?'

        matches = re.findall(pattern, content, re.I)
        seen_seasons = set()
        seasons_list = []

        for season_num, split, tier, division in matches:
            # Skip future seasons
            if int(season_num) >= 2026 or int(season_num) == 16:
                continue

            # Format season name
            base_season = f"S{season_num}"

            if split:
                split_match = re.search(r'Split\s*(\d)', split, re.I)
                if split_match:
                    season = f"{base_season} S{split_match.group(1)}"
                else:
                    season = base_season
            else:
                season = base_season

            if season in seen_seasons:
                continue
            seen_seasons.add(season)

            rank = division.upper() if division else ""

            seasons_list.append({
                "season": season,
                "data": [{
                    "queue": "Solo/Duo",
                    "tier": tier.capitalize(),
                    "rank": rank,
                    "lp": 0,
                    "wins": 0,
                    "losses": 0,
                    "winrate": 0
                }]
            })

        # Sort by season (newest first)
        seasons_list.sort(key=lambda x: season_sort_key(x["season"]), reverse=True)

        # Convert to dict preserving order
        history = {}
        for item in seasons_list:
            history[item["season"]] = item["data"]

        return history

    except Exception as e:
        print(f"Error scraping leagueofgraphs: {e}")
        return {}

def load_champions():
    global CHAMPIONS, DDRAGON_VERSION
    try:
        versions_url = "https://ddragon.leagueoflegends.com/api/versions.json"
        response = requests.get(versions_url)
        if response.status_code == 200:
            DDRAGON_VERSION = response.json()[0]

        url = f"https://ddragon.leagueoflegends.com/cdn/{DDRAGON_VERSION}/data/en_US/champion.json"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()["data"]
            CHAMPIONS = {int(champ["key"]): {"name": champ["name"], "id": champ["id"]} for champ in data.values()}
    except:
        pass

def fetch_player_stats(game_name: str, tag_line: str, region: str = "eun1", match_count: int = 30):
    headers = {"X-Riot-Token": API_KEY}
    routing = "europe" if region in ["eun1", "euw1", "tr1", "ru"] else "americas" if region in ["na1", "br1", "la1", "la2"] else "asia"

    result = {
        "success": False,
        "error": None,
        "player": None,
        "gameName": game_name,
        "tagLine": tag_line,
        "region": region,
        "level": None,
        "profileIcon": None,
        "puuid": None,
        "ranked": [],
        "season_history": {},
        "top_champions": [],
        "side_stats": None,
        "match_history": [],
        "ddragon_version": DDRAGON_VERSION,
        "current_season": CURRENT_SEASON,
        "updated_at": int(time.time())
    }

    # Step 1: Get PUUID
    account_url = f"https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
    response = requests.get(account_url, headers=headers)

    if response.status_code != 200:
        result["error"] = "Player not found. Check the Riot ID and tag."
        return result

    account_data = response.json()
    puuid = account_data["puuid"]
    result["puuid"] = puuid
    result["player"] = f"{account_data['gameName']}#{account_data['tagLine']}"
    result["gameName"] = account_data["gameName"]
    result["tagLine"] = account_data["tagLine"]

    # Step 2: Get Summoner data
    summoner_url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
    response = requests.get(summoner_url, headers=headers)

    if response.status_code == 200:
        summoner_data = response.json()
        result["level"] = summoner_data["summonerLevel"]
        result["profileIcon"] = summoner_data["profileIconId"]

    # Step 3: Get ranked stats
    ranked_url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
    response = requests.get(ranked_url, headers=headers)

    if response.status_code == 200:
        for queue in response.json():
            queue_type = "Solo/Duo" if queue["queueType"] == "RANKED_SOLO_5x5" else "Flex"
            tier = queue["tier"].capitalize()
            rank = queue["rank"]
            lp = queue["leaguePoints"]
            wins = queue["wins"]
            losses = queue["losses"]
            winrate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0

            result["ranked"].append({
                "queue": queue_type,
                "tier": tier,
                "tierLower": tier.lower(),
                "rank": rank,
                "lp": lp,
                "wins": wins,
                "losses": losses,
                "winrate": round(winrate, 1)
            })

    # Season history will be fetched by lookup()

    # Step 4: Get match history
    matches_url = f"https://{routing}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?type=ranked&count={match_count}"
    response = requests.get(matches_url, headers=headers)

    if response.status_code != 200:
        result["success"] = True
        return result

    match_ids = response.json()

    champ_stats = defaultdict(lambda: {"wins": 0, "losses": 0})
    side_stats = {"blue": {"wins": 0, "losses": 0}, "red": {"wins": 0, "losses": 0}}

    match_history = []

    for match_id in match_ids:
        match_url = f"https://{routing}.api.riotgames.com/lol/match/v5/matches/{match_id}"
        response = requests.get(match_url, headers=headers)

        if response.status_code != 200:
            continue

        match_data = response.json()
        match_info = match_data["info"]

        for participant in match_info["participants"]:
            if participant["puuid"] == puuid:
                champ_id = participant["championId"]
                won = participant["win"]
                team_id = participant["teamId"]

                if won:
                    champ_stats[champ_id]["wins"] += 1
                else:
                    champ_stats[champ_id]["losses"] += 1

                side = "blue" if team_id == 100 else "red"
                if won:
                    side_stats[side]["wins"] += 1
                else:
                    side_stats[side]["losses"] += 1

                # Collect match history details
                champ_data = CHAMPIONS.get(champ_id, {"name": f"Champion {champ_id}", "id": "Unknown"})

                # Collect all participants data
                participants_data = []
                for p in match_info["participants"]:
                    p_champ_id = p["championId"]
                    p_champ_data = CHAMPIONS.get(p_champ_id, {"name": f"Champion {p_champ_id}", "id": "Unknown"})
                    # Extract full rune data
                    perks = p.get("perks", {})
                    styles = perks.get("styles", [])
                    primary_style = styles[0] if len(styles) > 0 else {}
                    secondary_style = styles[1] if len(styles) > 1 else {}

                    participants_data.append({
                        "puuid": p["puuid"],
                        "summonerName": p.get("riotIdGameName", p.get("summonerName", "Unknown")),
                        "tagLine": p.get("riotIdTagline", ""),
                        "champion": p_champ_data["name"],
                        "championId": p_champ_data["id"],
                        "teamId": p["teamId"],
                        "win": p["win"],
                        "kills": p["kills"],
                        "deaths": p["deaths"],
                        "assists": p["assists"],
                        "cs": p["totalMinionsKilled"] + p.get("neutralMinionsKilled", 0),
                        "gold": p["goldEarned"],
                        "damage": p["totalDamageDealtToChampions"],
                        "items": [p.get(f"item{i}", 0) for i in range(7)],
                        "summoner1": p.get("summoner1Id", 0),
                        "summoner2": p.get("summoner2Id", 0),
                        "primaryRune": primary_style.get("style", 0),
                        "secondaryRune": secondary_style.get("style", 0),
                        "runes": {
                            "primary": {
                                "style": primary_style.get("style", 0),
                                "perks": [s.get("perk", 0) for s in primary_style.get("selections", [])]
                            },
                            "secondary": {
                                "style": secondary_style.get("style", 0),
                                "perks": [s.get("perk", 0) for s in secondary_style.get("selections", [])]
                            },
                            "statPerks": perks.get("statPerks", {})
                        }
                    })

                # Extract full rune data for current player
                player_perks = participant.get("perks", {})
                player_styles = player_perks.get("styles", [])
                player_primary = player_styles[0] if len(player_styles) > 0 else {}
                player_secondary = player_styles[1] if len(player_styles) > 1 else {}

                match_history.append({
                    "matchId": match_id,
                    "champion": champ_data["name"],
                    "championId": champ_data["id"],
                    "win": won,
                    "kills": participant["kills"],
                    "deaths": participant["deaths"],
                    "assists": participant["assists"],
                    "cs": participant["totalMinionsKilled"] + participant.get("neutralMinionsKilled", 0),
                    "gold": participant["goldEarned"],
                    "damage": participant["totalDamageDealtToChampions"],
                    "items": [participant.get(f"item{i}", 0) for i in range(7)],
                    "summoner1": participant.get("summoner1Id", 0),
                    "summoner2": participant.get("summoner2Id", 0),
                    "primaryRune": player_primary.get("style", 0),
                    "secondaryRune": player_secondary.get("style", 0),
                    "runes": {
                        "primary": {
                            "style": player_primary.get("style", 0),
                            "perks": [s.get("perk", 0) for s in player_primary.get("selections", [])]
                        },
                        "secondary": {
                            "style": player_secondary.get("style", 0),
                            "perks": [s.get("perk", 0) for s in player_secondary.get("selections", [])]
                        },
                        "statPerks": player_perks.get("statPerks", {})
                    },
                    "duration": match_info["gameDuration"],
                    "timestamp": match_info["gameStartTimestamp"],
                    "gameMode": match_info.get("gameMode", "CLASSIC"),
                    "queueId": match_info.get("queueId", 0),
                    "participants": participants_data
                })
                break

    result["match_history"] = match_history

    # Top 3 champions
    champ_winrates = []
    for champ_id, stats in champ_stats.items():
        total = stats["wins"] + stats["losses"]
        if total >= 3:
            wr = (stats["wins"] / total) * 100
            champ_data = CHAMPIONS.get(champ_id, {"name": f"Champion {champ_id}", "id": "Unknown"})
            champ_winrates.append({
                "name": champ_data["name"],
                "id": champ_data["id"],
                "wins": stats["wins"],
                "losses": stats["losses"],
                "winrate": round(wr, 1),
                "games": total
            })

    champ_winrates.sort(key=lambda x: (-x["winrate"], -x["games"]))
    result["top_champions"] = champ_winrates[:3]

    # Side stats
    blue_total = side_stats["blue"]["wins"] + side_stats["blue"]["losses"]
    red_total = side_stats["red"]["wins"] + side_stats["red"]["losses"]

    blue_wr = (side_stats["blue"]["wins"] / blue_total * 100) if blue_total > 0 else 0
    red_wr = (side_stats["red"]["wins"] / red_total * 100) if red_total > 0 else 0

    result["side_stats"] = {
        "blue": {
            "wins": side_stats["blue"]["wins"],
            "losses": side_stats["blue"]["losses"],
            "winrate": round(blue_wr, 1),
            "better": blue_wr > red_wr
        },
        "red": {
            "wins": side_stats["red"]["wins"],
            "losses": side_stats["red"]["losses"],
            "winrate": round(red_wr, 1),
            "better": red_wr > blue_wr
        }
    }

    result["success"] = True
    return result


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/player/<game_name>/<tag_line>/<region>")
def player_page(game_name, tag_line, region):
    return render_template("index.html", prefill_name=game_name, prefill_tag=tag_line, prefill_region=region, auto_search=True)


def get_season_history(game_name, tag_line, region, force_refresh=False):
    """Get season history - from cache or fresh scrape"""
    if not force_refresh:
        cached, updated_at = get_cached_season_history(game_name, tag_line, region)
        if cached:
            return cached

    # Scrape fresh data
    history = scrape_season_history(game_name, tag_line, region)
    if history:
        save_season_history_cache(game_name, tag_line, region, history)
    return history


@app.route("/lookup", methods=["POST"])
def lookup():
    data = request.json
    game_name = data.get("gameName", "").strip()
    tag_line = data.get("tagLine", "").strip()
    region = data.get("region", "eun1")
    force_refresh = data.get("refresh", False)

    if not game_name or not tag_line:
        return jsonify({"success": False, "error": "Please enter both Game Name and Tag"})

    # Check cache first (unless force refresh)
    if not force_refresh:
        cached_data, updated_at = get_cached_player(game_name, tag_line, region)
        if cached_data:
            cached_data["from_cache"] = True
            cached_data["updated_at"] = updated_at
            # Only overwrite season_history if we get fresh data
            fresh_season_history = get_season_history(game_name, tag_line, region, force_refresh=False)
            if fresh_season_history:
                cached_data["season_history"] = fresh_season_history
            return jsonify(cached_data)

    # Fetch fresh data
    result = fetch_player_stats(game_name, tag_line, region)

    if result["success"]:
        result["from_cache"] = False
        # Get fresh season history and cache it
        result["season_history"] = get_season_history(result["gameName"], result["tagLine"], region, force_refresh=True)
        save_player(result["gameName"], result["tagLine"], region, result)

    return jsonify(result)


# Initialize on startup
init_db()
load_champions()

if __name__ == "__main__":
    import socket
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except:
        local_ip = "your-local-ip"

    print("Starting LoL Rank Checker...")
    print(f"Open http://localhost:5000 in your browser")
    print(f"Or access from other devices at http://{local_ip}:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
