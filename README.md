# LoL Rank Checker

A web application to look up League of Legends player statistics, match history, and season rankings.

## Features

- **Player Lookup** - Search any player by Riot ID (GameName#Tag)
- **Ranked Stats** - View Solo/Duo and Flex queue rankings with LP, wins/losses, and winrate
- **Season History** - Past season rankings scraped from LeagueOfGraphs
- **Top Champions** - Most played champions with winrate statistics
- **Side Stats** - Blue vs Red side winrate comparison
- **Match History** - Recent ranked games with:
  - Champion, KDA, CS, gold, damage
  - Expandable details showing all 10 players
  - Clickable player names to view their stats
  - Items with icons
  - Clickable runes with detailed popup (primary/secondary trees, stat shards)
- **Data Caching** - SQLite database caches player data for faster lookups
- **Shareable Links** - Direct URLs to player profiles (e.g., `/player/Name/Tag/eun1`)
- **Multi-Region Support** - EUW, EUNE, NA, KR, BR, TR, RU, LAN, LAS

## Tech Stack

- **Backend**: Python Flask
- **Frontend**: Vanilla HTML/CSS/JavaScript
- **Database**: SQLite
- **APIs**:
  - Riot Games API (player data, match history)
  - Data Dragon CDN (champion/item/rune icons)
  - LeagueOfGraphs (season history scraping)

## Setup

### Prerequisites

- Python 3.8+
- Riot Games API Key ([Get one here](https://developer.riotgames.com/))

### Installation

1. Clone the repository:
```bash
git clone https://github.com/ExisteRcz/lol-rank-checker.git
cd lol-rank-checker
```

2. Install dependencies:
```bash
pip install flask requests
```

3. Set your Riot API key (optional - uses default key if not set):
```bash
# Windows
set RIOT_API_KEY=your-api-key-here

# Linux/Mac
export RIOT_API_KEY=your-api-key-here
```

4. Run the application:
```bash
python app.py
```

5. Open http://localhost:5000 in your browser

## Configuration

Environment variables:
- `RIOT_API_KEY` - Your Riot Games API key
- `DB_PATH` - Path to SQLite database (default: `players.db`)

## Usage

1. Enter a player's Riot ID (e.g., `PlayerName#TAG`)
2. Select the region
3. Click "Search" or press Enter
4. View stats, click on matches to expand details
5. Click on player names in match details to look up their stats
6. Click on runes to see detailed rune information

## Project Structure

```
lol_rank_webapp/
├── app.py              # Flask backend
├── players.db          # SQLite cache database
├── templates/
│   └── index.html      # Frontend (HTML/CSS/JS)
└── README.md
```

## License

MIT License
