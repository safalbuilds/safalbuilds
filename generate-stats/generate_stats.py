import os
import requests
from datetime import datetime, timezone

USERNAME = "safalbuilds"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT   = os.path.dirname(SCRIPT_DIR)
ASSETS_DIR  = os.path.join(REPO_ROOT, "assets")
# TOKEN = os.environ.get("GH_TOKEN", "")
TOKEN = "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"

HEADERS = {
    "Authorization": f"bearer {TOKEN}",
    "Content-Type": "application/json",
}

# ── GraphQL query ─────────────────────────────────────────────────────────────

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

# ── Fetch + parse ─────────────────────────────────────────────────────────────

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
            name  = edge["node"]["name"]
            color = edge["node"]["color"] or "#858585"
            size  = edge["size"]
            if name not in lang_sizes:
                lang_sizes[name] = {"size": 0, "color": color}
            lang_sizes[name]["size"] += size

    total_size = sum(v["size"] for v in lang_sizes.values()) or 1
    top_langs  = sorted(lang_sizes.items(), key=lambda x: x[1]["size"], reverse=True)[:6]
    langs = [
        {"name": n, "color": v["color"], "percent": round(v["size"] / total_size * 100, 1)}
        for n, v in top_langs
    ]

    contrib  = user["contributionsCollection"]
    calendar = contrib["contributionCalendar"]
    all_days = [day for week in calendar["weeks"] for day in week["contributionDays"]]

    today = datetime.now(timezone.utc).date()
    current_streak = longest_streak = temp = 0
    for day in reversed(all_days):
        d = datetime.strptime(day["date"], "%Y-%m-%d").date()
        if d > today:
            continue
        if day["contributionCount"] > 0:
            temp += 1
            longest_streak = max(longest_streak, temp)
            if current_streak == 0:
                current_streak = temp
        else:
            if current_streak != 0:
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


# ── Theme ─────────────────────────────────────────────────────────────────────
# Base: #01000E  —  mixed with a blue-indigo palette

BG       = "#01000E"   # near-black base
CARD_BG  = "#05061A"   # slightly lighter deep navy
BORDER   = "#0D1535"   # subtle blue-tinted border
TEXT_PRI = "#C8D8F8"   # cool light blue-white
TEXT_SEC = "#4A6A9E"   # muted steel blue
ACCENT   = "#3B82F6"   # vivid blue
BLUE2    = "#60A5FA"   # lighter blue highlight
BLUE3    = "#93C5FD"   # soft blue for secondary values
PURPLE   = "#818CF8"   # indigo-purple accent
GLOW     = "#1D3461"   # deep blue for fill areas under line


def svg_header(width, height):
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg">\n'
        f'<style>\n'
        f'  text {{ font-family: "Segoe UI", Ubuntu, sans-serif; }}\n'
        f'  .title {{ font-size: 14px; font-weight: 700; fill: {BLUE2}; }}\n'
        f'  .label {{ font-size: 12px; fill: {TEXT_SEC}; }}\n'
        f'  .value {{ font-size: 13px; font-weight: 600; fill: {TEXT_PRI}; }}\n'
        f'  .sub   {{ font-size: 11px; fill: {TEXT_SEC}; }}\n'
        f'</style>\n'
        f'<rect width="{width}" height="{height}" rx="12" fill="{BG}"/>\n'
        f'<rect x="1" y="1" width="{width-2}" height="{height-2}" rx="11" '
        f'fill="{CARD_BG}" stroke="{BORDER}" stroke-width="1"/>\n'
    )


# ── Card 1: GitHub Stats ──────────────────────────────────────────────────────

def make_stats_svg(s):
    W, H = 495, 195
    rows = [
        ("Total Stars",     str(s["stars"]),    BLUE2),
        ("Total Commits",   str(s["commits"]),  ACCENT),
        ("Pull Requests",   str(s["prs"]),      PURPLE),
        ("Issues",          str(s["issues"]),   BLUE3),
        ("Contributed To",  str(s["repos"]),    BLUE2),
        ("Followers",       str(s["followers"]),ACCENT),
    ]

    out = svg_header(W, H)
    out += f'<text x="25" y="35" class="title">GitHub Stats</text>\n'

    # accent line under title
    out += f'<line x1="25" y1="45" x2="{W-25}" y2="45" stroke="{BORDER}" stroke-width="0.5"/>\n'

    for i, (label, value, color) in enumerate(rows):
        col = i % 2
        row = i // 2
        x_label = 40 + col * 240
        x_value = 228 + col * 240
        y = 72 + row * 36

        # small colored square indicator
        out += f'<rect x="{x_label-14}" y="{y-9}" width="6" height="6" rx="1" fill="{color}" opacity="0.8"/>\n'
        out += f'<text x="{x_label}" y="{y}" class="label">{label}</text>\n'
        out += f'<text x="{x_value}" y="{y}" class="value" text-anchor="end" fill="{color}">{value}</text>\n'

    # bottom progress bar
    filled = int(min(s["total_contributions"] / 1000 * (W - 50), W - 50))
    out += f'<rect x="25" y="{H-20}" width="{W-50}" height="2" rx="1" fill="{BORDER}"/>\n'
    out += f'<rect x="25" y="{H-20}" width="{filled}" height="2" rx="1" fill="{ACCENT}"/>\n'
    out += f'<text x="25" y="{H-6}" class="sub">{s["total_contributions"]} contributions this year</text>\n'

    out += "</svg>"
    return out


# ── Card 2: Streak Stats ──────────────────────────────────────────────────────

def make_streak_svg(s):
    W, H = 495, 195

    out = svg_header(W, H)
    out += f'<text x="{W//2}" y="32" class="title" text-anchor="middle">GitHub Streak</text>\n'
    out += f'<line x1="25" y1="42" x2="{W-25}" y2="42" stroke="{BORDER}" stroke-width="0.5"/>\n'

    sections = [
        ("Total Contributions", str(s["total_contributions"]), ACCENT),
        ("Current Streak",      f'{s["current_streak"]} days', BLUE2),
        ("Longest Streak",      f'{s["longest_streak"]} days', PURPLE),
    ]

    for i, (label, value, color) in enumerate(sections):
        cx = 83 + i * 165
        if i > 0:
            out += f'<line x1="{cx-82}" y1="50" x2="{cx-82}" y2="{H-30}" stroke="{BORDER}" stroke-width="0.5"/>\n'

        out += (
            f'<text x="{cx}" y="108" font-family="Segoe UI,Ubuntu,sans-serif" '
            f'font-size="30" font-weight="700" fill="{color}" text-anchor="middle">{value}</text>\n'
        )
        out += f'<text x="{cx}" y="138" class="sub" text-anchor="middle">{label}</text>\n'

        # small dot under label
        out += f'<circle cx="{cx}" cy="{H-20}" r="3" fill="{color}" opacity="0.5"/>\n'

    out += "</svg>"
    return out


# ── Card 3: Top Languages ─────────────────────────────────────────────────────

def make_langs_svg(s):
    W, H = 504, 205
    langs = s["langs"]

    out = svg_header(W, H)
    out += f'<text x="20" y="32" class="title">Top Languages</text>\n'
    out += f'<line x1="20" y1="42" x2="{W-20}" y2="42" stroke="{BORDER}" stroke-width="0.5"/>\n'

    bar_x, bar_y, bar_w, bar_h = 20, 52, W - 40, 7
    out += f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="3" fill="{BORDER}"/>\n'

    offset = 0
    for lang in langs:
        seg_w = max(int(bar_w * lang["percent"] / 100), 2)
        out += f'<rect x="{bar_x+offset}" y="{bar_y}" width="{seg_w}" height="{bar_h}" fill="{lang["color"]}"/>\n'
        offset += seg_w

    col_count = 2
    col_width = (W - 40) // col_count

    for i, lang in enumerate(langs):
        col = i % col_count
        row = i // col_count
        x = 20 + col * int(col_width)
        y = 82 + row * 36
        out += f'<circle cx="{x+6}" cy="{y}" r="5" fill="{lang["color"]}"/>\n'
        out += f'<text x="{x+16}" y="{y+4}" class="label">{lang["name"]}</text>\n'
        percent_x = x + int(col_width) - 12
        out += f'<text x="{percent_x}" y="{y+4}" class="sub" text-anchor="end">{lang["percent"]}%</text>\n'
    out += "</svg>"
    return out


# ── Card 4: Contribution Line Curve ──────────────────────────────────────────

def make_graph_svg(s):
    W, H = 495, 160

    # use last 90 days for a clean curve
    all_days = s["all_days"]
    days_90  = all_days[-90:] if len(all_days) >= 90 else all_days
    counts   = [d["contributionCount"] for d in days_90]
    dates    = [d["date"] for d in days_90]

    CHART_X  = 20
    CHART_Y  = 30
    CHART_W  = W - 40
    CHART_H  = 90
    n        = len(counts)
    max_c    = max(counts) if max(counts) > 0 else 1

    def px(i, c):
        x = CHART_X + int(i / (n - 1) * CHART_W) if n > 1 else CHART_X
        y = CHART_Y + CHART_H - int(c / max_c * CHART_H)
        return x, y

    # build smooth cubic bezier path
    points = [px(i, c) for i, c in enumerate(counts)]

    def smooth_path(pts):
        if len(pts) < 2:
            return f"M {pts[0][0]} {pts[0][1]}"
        d = f"M {pts[0][0]} {pts[0][1]}"
        for i in range(1, len(pts)):
            x0, y0 = pts[i-1]
            x1, y1 = pts[i]
            cx = (x0 + x1) // 2
            d += f" C {cx} {y0}, {cx} {y1}, {x1} {y1}"
        return d

    line_d = smooth_path(points)

    # area fill path (close below)
    bx, by = points[0]
    ex, ey = points[-1]
    area_d = line_d + f" L {ex} {CHART_Y+CHART_H} L {bx} {CHART_Y+CHART_H} Z"

    out = svg_header(W, H)

    # defs: gradient fill under curve
    out += (
        f'<defs>\n'
        f'  <linearGradient id="areafill" x1="0" y1="0" x2="0" y2="1">\n'
        f'    <stop offset="0%" stop-color="{ACCENT}" stop-opacity="0.35"/>\n'
        f'    <stop offset="100%" stop-color="{BG}" stop-opacity="0"/>\n'
        f'  </linearGradient>\n'
        f'</defs>\n'
    )

    out += f'<text x="20" y="20" class="title">Contribution Activity</text>\n'

    # horizontal grid lines
    for step in [0.25, 0.5, 0.75, 1.0]:
        gy = CHART_Y + CHART_H - int(step * CHART_H)
        out += f'<line x1="{CHART_X}" y1="{gy}" x2="{CHART_X+CHART_W}" y2="{gy}" stroke="{BORDER}" stroke-width="0.5" stroke-dasharray="3,4"/>\n'

    # area fill
    out += f'<path d="{area_d}" fill="url(#areafill)"/>\n'

    # line
    out += f'<path d="{line_d}" fill="none" stroke="{ACCENT}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>\n'

    # dots at peaks
    peak_val = max(counts)
    for i, c in enumerate(counts):
        if c == peak_val:
            px_, py_ = points[i]
            out += f'<circle cx="{px_}" cy="{py_}" r="3" fill="{BLUE2}" stroke="{BG}" stroke-width="1.5"/>\n'

    # month labels along bottom
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    last_month = None
    for i, date_str in enumerate(dates):
        m = datetime.strptime(date_str, "%Y-%m-%d").month
        if m != last_month:
            lx, _ = points[i]
            out += f'<text x="{lx}" y="{CHART_Y+CHART_H+16}" class="sub" text-anchor="middle">{months[m-1]}</text>\n'
            last_month = m

    # baseline
    out += f'<line x1="{CHART_X}" y1="{CHART_Y+CHART_H}" x2="{CHART_X+CHART_W}" y2="{CHART_Y+CHART_H}" stroke="{BORDER}" stroke-width="0.5"/>\n'

    out += "</svg>"
    return out


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Fetching GitHub data...")
    user  = fetch_data()
    stats = parse_stats(user)

    print(f"  Name:          {stats['name']}")
    print(f"  Stars:         {stats['stars']}")
    print(f"  Commits:       {stats['commits']}")
    print(f"  Streak:        {stats['current_streak']} days")
    print(f"  Contributions: {stats['total_contributions']}")

    os.makedirs(ASSETS_DIR, exist_ok=True)

    for name, fn in [
        ("stats.svg",  make_stats_svg),
        ("streak.svg", make_streak_svg),
        ("langs.svg",  make_langs_svg),
        ("graph.svg",  make_graph_svg),
    ]:
        path = os.path.join(ASSETS_DIR, name)
        with open(path, "w") as f:
            f.write(fn(stats))
        print(f"  ✓ {path}")

    print("Done.")


if __name__ == "__main__":
    main()