from flask import Flask, render_template, request, jsonify, redirect, url_for
import requests
from collections import defaultdict
import sqlite3
import json
import time
import os

app = Flask(__name__)

# Use environment variable for API key in production
API_KEY = os.environ.get("RIOT_API_KEY", "RGAPI-a68d3734-f59b-4a4a-b688-fb4ddce0c125")
CHAMPIONS = {}
DDRAGON_VERSION = "14.24.1"
DB_PATH = os.environ.get("DB_PATH", "players.db")

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
        "ranked": [],
        "top_champions": [],
        "side_stats": None,
        "ddragon_version": DDRAGON_VERSION,
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

    # Step 4: Get match history
    matches_url = f"https://{routing}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?type=ranked&count={match_count}"
    response = requests.get(matches_url, headers=headers)

    if response.status_code != 200:
        result["success"] = True
        return result

    match_ids = response.json()

    champ_stats = defaultdict(lambda: {"wins": 0, "losses": 0})
    side_stats = {"blue": {"wins": 0, "losses": 0}, "red": {"wins": 0, "losses": 0}}

    for match_id in match_ids:
        match_url = f"https://{routing}.api.riotgames.com/lol/match/v5/matches/{match_id}"
        response = requests.get(match_url, headers=headers)

        if response.status_code != 200:
            continue

        match_data = response.json()

        for participant in match_data["info"]["participants"]:
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
                break

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
            return jsonify(cached_data)

    # Fetch fresh data
    result = fetch_player_stats(game_name, tag_line, region)

    if result["success"]:
        result["from_cache"] = False
        save_player(result["gameName"], result["tagLine"], region, result)

    return jsonify(result)


# Initialize on startup
init_db()
load_champions()

if __name__ == "__main__":
    print("Starting LoL Rank Checker...")
    print("Open http://localhost:5000 in your browser")
    app.run(debug=True, port=5000)
