import os
import requests
from datetime import datetime, timezone

USERNAME = "safalbuilds"

# Always save assets relative to repo root (one level up from this script)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT   = os.path.dirname(SCRIPT_DIR)
ASSETS_DIR  = os.path.join(REPO_ROOT, "assets")
TOKEN = os.environ.get("GH_TOKEN", "")

HEADERS = {
    "Authorization": f"bearer {TOKEN}",
    "Content-Type": "application/json",
}

# ── GraphQL query ────────────────────────────────────────────────────────────

QUERY = """
query($username: String!) {
  user(login: $username) {
    name
    login
    followers { totalCount }
    following { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node { name color }
          }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalRepositoryContributions
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            date
          }
        }
      }
    }
  }
}
"""

# ── Fetch data ────────────────────────────────────────────────────────────────

def fetch_data():
    response = requests.post(
        "https://api.github.com/graphql",
        json={"query": QUERY, "variables": {"username": USERNAME}},
        headers=HEADERS,
    )
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        raise Exception(f"GraphQL errors: {data['errors']}")
    return data["data"]["user"]


def parse_stats(user):
    repos = user["repositories"]["nodes"]

    total_stars = sum(r["stargazerCount"] for r in repos)

    lang_sizes = {}
    for repo in repos:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            color = edge["node"]["color"] or "#858585"
            size = edge["size"]
            if name not in lang_sizes:
                lang_sizes[name] = {"size": 0, "color": color}
            lang_sizes[name]["size"] += size

    total_size = sum(v["size"] for v in lang_sizes.values()) or 1
    top_langs = sorted(lang_sizes.items(), key=lambda x: x[1]["size"], reverse=True)[:6]
    langs = [
        {"name": n, "color": v["color"], "percent": round(v["size"] / total_size * 100, 1)}
        for n, v in top_langs
    ]

    contrib = user["contributionsCollection"]
    calendar = contrib["contributionCalendar"]
    all_days = [
        day
        for week in calendar["weeks"]
        for day in week["contributionDays"]
    ]

    # streak calculation
    today = datetime.now(timezone.utc).date()
    current_streak = 0
    longest_streak = 0
    temp = 0
    for day in reversed(all_days):
        d = datetime.strptime(day["date"], "%Y-%m-%d").date()
        if d > today:
            continue
        if day["contributionCount"] > 0:
            temp += 1
            if temp > longest_streak:
                longest_streak = temp
            if current_streak == 0 or d >= today:
                current_streak = temp
        else:
            if current_streak == 0:
                pass
            temp = 0

    return {
        "name": user["name"] or user["login"],
        "login": user["login"],
        "followers": user["followers"]["totalCount"],
        "following": user["following"]["totalCount"],
        "stars": total_stars,
        "commits": contrib["totalCommitContributions"],
        "prs": contrib["totalPullRequestContributions"],
        "issues": contrib["totalIssueContributions"],
        "repos": contrib["totalRepositoryContributions"],
        "total_contributions": calendar["totalContributions"],
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "langs": langs,
        "all_days": all_days,
    }


# ── SVG helpers ───────────────────────────────────────────────────────────────

BG        = "#1F222E"
CARD_BG   = "#262B3D"
BORDER    = "#2E3250"
TEXT_PRI  = "#E8EAF6"
TEXT_SEC  = "#8892B0"
ACCENT    = "#58A6FF"
GREEN     = "#3ABEFF"
PURPLE    = "#A78BFA"
GOLD      = "#F1C40F"

def svg_header(width, height):
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg">\n'
        f'<style>\n'
        f'  text {{ font-family: "Segoe UI", Ubuntu, sans-serif; }}\n'
        f'  .title {{ font-size: 14px; font-weight: 700; fill: {ACCENT}; }}\n'
        f'  .label {{ font-size: 12px; fill: {TEXT_SEC}; }}\n'
        f'  .value {{ font-size: 13px; font-weight: 600; fill: {TEXT_PRI}; }}\n'
        f'  .big   {{ font-size: 28px; font-weight: 700; fill: {TEXT_PRI}; }}\n'
        f'  .sub   {{ font-size: 11px; fill: {TEXT_SEC}; }}\n'
        f'</style>\n'
        f'<rect width="{width}" height="{height}" rx="12" fill="{BG}" />\n'
        f'<rect x="1" y="1" width="{width-2}" height="{height-2}" rx="11" '
        f'fill="{CARD_BG}" stroke="{BORDER}" stroke-width="1"/>\n'
    )


# ── Card 1: GitHub Stats ──────────────────────────────────────────────────────

def make_stats_svg(s):
    W, H = 495, 195
    rows = [
        ("⭐ Total Stars",      str(s["stars"])),
        ("🔨 Total Commits",    str(s["commits"])),
        ("🔀 Pull Requests",    str(s["prs"])),
        ("🐛 Issues",           str(s["issues"])),
        ("📦 Contributed To",   str(s["repos"])),
        ("👥 Followers",        str(s["followers"])),
    ]

    out = svg_header(W, H)
    out += f'<text x="25" y="35" class="title">📊 {s["name"]}\'s GitHub Stats</text>\n'

    for i, (label, value) in enumerate(rows):
        col = i % 2
        row = i // 2
        x_label = 25 + col * 240
        x_value = 220 + col * 240
        y = 70 + row * 38
        # dot
        out += f'<circle cx="{x_label - 8}" cy="{y - 4}" r="3" fill="{ACCENT}" opacity="0.6"/>\n'
        out += f'<text x="{x_label}" y="{y}" class="label">{label}</text>\n'
        out += f'<text x="{x_value}" y="{y}" class="value" text-anchor="end">{value}</text>\n'

    # bottom bar
    out += f'<rect x="25" y="{H-18}" width="445" height="3" rx="2" fill="{BORDER}"/>\n'
    filled = int(min(s["total_contributions"] / 1000 * 445, 445))
    out += f'<rect x="25" y="{H-18}" width="{filled}" height="3" rx="2" fill="{ACCENT}"/>\n'
    out += f'<text x="25" y="{H-4}" class="sub">{s["total_contributions"]} contributions this year</text>\n'

    out += "</svg>"
    return out


# ── Card 2: Streak Stats ──────────────────────────────────────────────────────

def make_streak_svg(s):
    W, H = 495, 195

    out = svg_header(W, H)
    out += f'<text x="{W//2}" y="30" class="title" text-anchor="middle">🔥 GitHub Streak</text>\n'

    sections = [
        ("Total\nContributions", str(s["total_contributions"]), ACCENT),
        ("Current\nStreak",      f'{s["current_streak"]} days', GREEN),
        ("Longest\nStreak",      f'{s["longest_streak"]} days', PURPLE),
    ]

    for i, (label, value, color) in enumerate(sections):
        cx = 83 + i * 165
        # divider
        if i > 0:
            out += f'<line x1="{cx - 82}" y1="50" x2="{cx - 82}" y2="{H-30}" stroke="{BORDER}" stroke-width="1"/>\n'
        # value
        out += f'<text x="{cx}" y="105" font-family="Segoe UI,Ubuntu,sans-serif" font-size="30" font-weight="700" fill="{color}" text-anchor="middle">{value}</text>\n'
        # label (two lines)
        lines = label.split("\n")
        for j, line in enumerate(lines):
            out += f'<text x="{cx}" y="{140 + j*16}" class="sub" text-anchor="middle">{line}</text>\n'

    out += "</svg>"
    return out


# ── Card 3: Top Languages ─────────────────────────────────────────────────────

def make_langs_svg(s):
    W, H = 300, 200
    langs = s["langs"]

    out = svg_header(W, H)
    out += f'<text x="20" y="32" class="title">💻 Top Languages</text>\n'

    # progress bar
    bar_x = 20
    bar_y = 48
    bar_w = W - 40
    bar_h = 8
    out += f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="4" fill="{BORDER}"/>\n'

    offset = 0
    for lang in langs:
        seg_w = int(bar_w * lang["percent"] / 100)
        if seg_w < 1:
            seg_w = 1
        out += f'<rect x="{bar_x + offset}" y="{bar_y}" width="{seg_w}" height="{bar_h}" fill="{lang["color"]}"/>\n'
        offset += seg_w

    # legend
    for i, lang in enumerate(langs):
        col = i % 2
        row = i // 2
        x = 20 + col * 145
        y = 80 + row * 36
        out += f'<circle cx="{x + 6}" cy="{y}" r="5" fill="{lang["color"]}"/>\n'
        out += f'<text x="{x + 16}" y="{y + 4}" class="label">{lang["name"]}</text>\n'
        out += f'<text x="{x + 130}" y="{y + 4}" class="sub" text-anchor="end">{lang["percent"]}%</text>\n'

    out += "</svg>"
    return out


# ── Card 4: Contribution Graph ────────────────────────────────────────────────

def make_graph_svg(s):
    W, H = 495, 150
    all_days = s["all_days"][-364:]  # last 52 weeks

    CELL = 10
    GAP  = 2
    OFF_X = 20
    OFF_Y = 30

    max_count = max((d["contributionCount"] for d in all_days), default=1) or 1

    def day_color(count):
        if count == 0:
            return BORDER
        ratio = count / max_count
        if ratio < 0.25:
            return "#1e3a5f"
        elif ratio < 0.5:
            return "#1a6091"
        elif ratio < 0.75:
            return "#1e90d4"
        else:
            return ACCENT

    out = svg_header(W, H)
    out += f'<text x="20" y="20" class="title">📈 Contribution Graph</text>\n'

    # group into weeks
    weeks = [all_days[i:i+7] for i in range(0, len(all_days), 7)]

    for wi, week in enumerate(weeks):
        for di, day in enumerate(week):
            x = OFF_X + wi * (CELL + GAP)
            y = OFF_Y + di * (CELL + GAP)
            color = day_color(day["contributionCount"])
            out += f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="{color}"/>\n'

    # month labels
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    last_month = None
    for wi, week in enumerate(weeks):
        if week:
            month = datetime.strptime(week[0]["date"], "%Y-%m-%d").month
            if month != last_month:
                x = OFF_X + wi * (CELL + GAP)
                out += f'<text x="{x}" y="{H - 5}" class="sub">{months[month-1]}</text>\n'
                last_month = month

    out += "</svg>"
    return out


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Fetching GitHub data...")
    user = fetch_data()
    stats = parse_stats(user)

    print(f"  Name:         {stats['name']}")
    print(f"  Stars:        {stats['stars']}")
    print(f"  Commits:      {stats['commits']}")
    print(f"  Streak:       {stats['current_streak']} days")
    print(f"  Contributions:{stats['total_contributions']}")

    os.makedirs(ASSETS_DIR, exist_ok=True)

    for name, fn in [("stats.svg", make_stats_svg), ("streak.svg", make_streak_svg), ("langs.svg", make_langs_svg), ("graph.svg", make_graph_svg)]:
        path = os.path.join(ASSETS_DIR, name)
        svg_fn = fn(stats)
        with open(path, "w") as f:
            f.write(svg_fn)
        print(f"  ✓ {path}")

    print("Done.")


if __name__ == "__main__":
    main()