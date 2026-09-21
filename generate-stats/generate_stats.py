#!/usr/bin/env python3
"""
generate-stats/generate_stats.py

Runs inside the "Generate GitHub Stats" workflow. Fetches the repo owner's
GitHub stats and writes three animated SVG cards into assets/:

    assets/stats.svg   - full stats card
    assets/lang.svg    - compact top-languages card
    assets/graph.svg   - contribution activity line chart

No CLI args needed - everything is driven by environment variables, most
of which the workflow already sets for you:

    GH_TOKEN / GITHUB_TOKEN   auth token (workflow passes secrets.GITHUB_TOKEN)
    GITHUB_REPOSITORY         "owner/repo", used to infer the username
    GH_USERNAME               override the inferred username
    STATS_THEME               default: tokyonight
    HIDE_BORDER               "true"/"false", default: true
    INCLUDE_ALL_COMMITS       "true"/"false", default: true
    OUTPUT_DIR                default: assets
"""

from __future__ import annotations

import datetime
import os
import sys
import time
from dataclasses import dataclass, field

import requests

API = "https://api.github.com"

# --------------------------------------------------------------------------
# Themes
# --------------------------------------------------------------------------

THEMES = {
    "default": dict(bg="#fffefe", title="#2f80ed", icon="#4c71f2",
                    text="#434d58", muted="#586069", track="#ddd", border="#e4e2e2"),
    "dark": dict(bg="#151515", title="#fff", icon="#79ff97",
                 text="#9f9f9f", muted="#9f9f9f", track="#333", border="#e4e2e2"),
    "radical": dict(bg="#141321", title="#fe428e", icon="#f8d847",
                     text="#a9fef7", muted="#a9fef7", track="#2e2c47", border="#e4e2e2"),
    "dracula": dict(bg="#282a36", title="#ff79c6", icon="#ff79c6",
                     text="#f8f8f2", muted="#f8f8f2", track="#3f4257", border="#e4e2e2"),
    "tokyonight": dict(bg="#1a1b27", title="#70a5fd", icon="#bf91f3",
                        text="#38bdae", muted="#9aa5ce", track="#2e2f42", border="#70a5fd"),
}

LANGUAGE_COLORS = {
    "TypeScript": "#3178c6", "JavaScript": "#f1e05a", "Python": "#3572A5",
    "HTML": "#e34c26", "CSS": "#563d7c", "Java": "#b07219", "Go": "#00ADD8",
    "Rust": "#dea584", "C++": "#f34b7d", "C": "#555555", "Shell": "#89e051",
    "Ruby": "#701516", "PHP": "#4F5D95", "Jupyter Notebook": "#DA5B0B",
    "Vue": "#41b883", "Dart": "#00B4AB", "Kotlin": "#A97BFF",
}
FALLBACK_COLORS = ["#70a5fd", "#bf91f3", "#38bdae", "#f1e05a", "#e34c26", "#9aa5ce"]


def theme_or_default(name: str) -> dict:
    if name not in THEMES:
        print(f"[warn] unknown theme '{name}', falling back to 'default'. "
              f"Available: {', '.join(THEMES)}", file=sys.stderr)
        return THEMES["default"]
    return THEMES[name]


# --------------------------------------------------------------------------
# GitHub data fetching
# --------------------------------------------------------------------------

@dataclass
class Stats:
    username: str
    stars: int = 0
    commits: int = 0
    prs: int = 0
    issues: int = 0
    contributed_to: int = 0
    languages: dict = field(default_factory=dict)


class GitHubClient:
    def __init__(self, token: str | None = None):
        self.session = requests.Session()
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.session.headers.update(headers)

    def get(self, path: str, params: dict | None = None) -> dict:
        r = self.session.get(f"{API}{path}", params=params, timeout=20)
        if r.status_code == 403 and "rate limit" in r.text.lower():
            raise RuntimeError(
                "GitHub API rate limit hit even with a token. This is unusual "
                "for the default GITHUB_TOKEN - check the token is being passed."
            )
        r.raise_for_status()
        return r.json()

    def paginated(self, path: str, params: dict | None = None):
        params = dict(params or {})
        params.setdefault("per_page", 100)
        page = 1
        while True:
            params["page"] = page
            data = self.get(path, params)
            items = data.get("items", data) if isinstance(data, dict) else data
            if not items:
                break
            yield from items
            if len(items) < params["per_page"]:
                break
            page += 1


def fetch_stats(username: str, token: str | None, include_all_commits: bool) -> Stats:
    gh = GitHubClient(token)
    stats = Stats(username=username)

    repos = list(gh.paginated(f"/users/{username}/repos", {"type": "owner"}))
    stats.stars = sum(r.get("stargazers_count", 0) for r in repos)

    lang_totals: dict[str, int] = {}
    for r in repos:
        if r.get("fork"):
            continue
        try:
            langs = gh.get(f"/repos/{username}/{r['name']}/languages")
        except Exception:
            langs = {r["language"]: 1} if r.get("language") else {}
        for lang, nbytes in langs.items():
            lang_totals[lang] = lang_totals.get(lang, 0) + nbytes
        time.sleep(0.02)
    stats.languages = lang_totals

    def search_count(query: str) -> int:
        try:
            return gh.get("/search/issues", {"q": query, "per_page": 1}).get("total_count", 0)
        except Exception as exc:
            print(f"[warn] search query failed ({query!r}): {exc}", file=sys.stderr)
            return 0

    stats.prs = search_count(f"author:{username} type:pr")
    stats.issues = search_count(f"author:{username} type:issue")
    stats.contributed_to = search_count(f"involves:{username} -author:{username}")

    branch_qualifier = "" if include_all_commits else " author-date:>2000-01-01"
    try:
        commit_data = gh.get("/search/commits", {
            "q": f"author:{username}{branch_qualifier}", "per_page": 1
        })
        stats.commits = commit_data.get("total_count", 0)
    except Exception as exc:
        print(f"[warn] commit search unavailable ({exc}); leaving commits at 0", file=sys.stderr)

    return stats


def fetch_contribution_calendar(username: str, token: str | None, days: int = 110) -> list[tuple[datetime.date, int]]:
    """Daily contribution counts for the last `days` days, oldest first.

    Uses the GraphQL contributionsCollection field (accurate, counts issues/
    PRs/reviews too, not just commits) when a token is available. Falls back
    to counting PushEvent commits from the public events feed (last ~90
    days only, approximate) if GraphQL isn't usable.
    """
    to_dt = datetime.datetime.utcnow()
    from_dt = to_dt - datetime.timedelta(days=days)

    if token:
        query = """
        query($login: String!, $from: DateTime!, $to: DateTime!) {
          user(login: $login) {
            contributionsCollection(from: $from, to: $to) {
              contributionCalendar {
                weeks { contributionDays { date contributionCount } }
              }
            }
          }
        }"""
        try:
            r = requests.post(
                f"{API}/graphql",
                json={"query": query, "variables": {
                    "login": username,
                    "from": from_dt.strftime("%Y-%m-%dT00:00:00Z"),
                    "to": to_dt.strftime("%Y-%m-%dT23:59:59Z"),
                }},
                headers={"Authorization": f"Bearer {token}"},
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()
            if data.get("errors"):
                raise RuntimeError(data["errors"])
            weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
            daily = []
            for wk in weeks:
                for d in wk["contributionDays"]:
                    daily.append((datetime.date.fromisoformat(d["date"]), d["contributionCount"]))
            daily.sort(key=lambda t: t[0])
            return daily
        except Exception as exc:
            print(f"[warn] GraphQL contribution calendar unavailable ({exc}); "
                  f"falling back to a public-events approximation.", file=sys.stderr)

    # Fallback: approximate from public events (max ~90 days, public activity only).
    gh = GitHubClient(token)
    counts: dict[datetime.date, int] = {}
    try:
        for ev in gh.paginated(f"/users/{username}/events/public"):
            if ev.get("type") != "PushEvent":
                continue
            day = datetime.datetime.strptime(ev["created_at"], "%Y-%m-%dT%H:%M:%SZ").date()
            counts[day] = counts.get(day, 0) + len(ev.get("payload", {}).get("commits", []))
    except Exception as exc:
        print(f"[warn] events fallback also failed ({exc}); graph will be flat.", file=sys.stderr)

    daily = []
    d = from_dt.date()
    while d <= to_dt.date():
        daily.append((d, counts.get(d, 0)))
        d += datetime.timedelta(days=1)
    return daily


# --------------------------------------------------------------------------
# SVG rendering (SMIL-animated, no JS)
# --------------------------------------------------------------------------

def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def shade(color: str, factor: float) -> str:
    """Return a hex color scaled by `factor` (1 = unchanged, <1 = darker)."""
    c = color.lstrip("#")
    rgb = [int(c[i:i + 2], 16) for i in (0, 2, 4)]
    return "#{:02x}{:02x}{:02x}".format(*[max(0, min(255, round(v * factor))) for v in rgb])


STAT_ICONS = {
    "Total Stars Earned": "M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.75.75 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z",
    "Total Commits": "M11.93 8.5a4.002 4.002 0 0 1-7.86 0H.75a.75.75 0 0 1 0-1.5h3.32a4.002 4.002 0 0 1 7.86 0h3.32a.75.75 0 0 1 0 1.5Zm-1.43-.75a2.5 2.5 0 1 0-5 0 2.5 2.5 0 0 0 5 0Z",
    "Total PRs": "M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.25 2.25 0 0 1 1.5 3.25Zm5.677-.177L9.573.677A.25.25 0 0 1 10 .854V2.5h1A2.5 2.5 0 0 1 13.5 5v5.628a2.251 2.251 0 1 1-1.5 0V5a1 1 0 0 0-1-1h-1v1.646a.25.25 0 0 1-.427.177L7.177 3.427a.25.25 0 0 1 0-.354ZM3.75 2.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm0 9.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm8.25.75a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Z",
    "Total Issues": "M8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3ZM8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0Zm0 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13Z",
    "Contributed to (last yr)": "M2 5.5a3.5 3.5 0 1 1 7 0 3.5 3.5 0 0 1-7 0Zm10.5 3.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5Zm.5 1.75a3.5 3.5 0 0 1 3.5 3.5 5 0 0 1-.5 2.25.75.75 0 0 1-1.31-.75.748.748 0 0 0 .31-.6 2 2 0 0 0-4 0c0 .24.12.46.31.6a.75.75 0 1 1-1.31.75 3.49 3.49 0 0 1 2.5-4.25ZM6.5 6.75a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm-3.879 4.754a5.5 5.5 0 0 1 7.758 0 .75.75 0 1 1-1.06 1.061 4 4 0 0 0-5.638 0 .75.75 0 0 1-1.06-1.061Z",
}


def render_stats_svg(stats: Stats, theme: dict, hide_border: bool, layout: str = "normal") -> str:
    W, H = (495, 130) if layout == "compact" else (495, 195)
    border_stroke = "none" if hide_border else theme["border"]

    rows = [
        ("Total Stars Earned", stats.stars),
        ("Total Commits", stats.commits),
        ("Total PRs", stats.prs),
        ("Total Issues", stats.issues),
        ("Contributed to (last yr)", stats.contributed_to),
    ]

    row_svgs = []
    if layout == "compact":
        col_w = (W - 40) / 2
        for i, (label, value) in enumerate(rows):
            col, r = divmod(i, 3)
            x = 20 + col * col_w
            y = 34 + r * 24
            delay = 0.15 * i
            row_svgs.append(f'''
      <g transform="translate({x},{y})" opacity="0">
        <animate attributeName="opacity" from="0" to="1" begin="{delay:.2f}s" dur="0.5s" fill="freeze"/>
        <text x="0" y="0" font-size="12" fill="{theme['muted']}">{esc(label)}:</text>
        <text x="{col_w-20}" y="0" font-size="12" font-weight="700" text-anchor="end" fill="{theme['text']}">{value:,}</text>
      </g>''')
        rank_svg = ""
    else:
        for i, (label, value) in enumerate(rows):
            y = 55 + i * 24
            delay = 0.15 * i
            icon = STAT_ICONS.get(label, "")
            icon_svg = f'''<path d="{icon}" fill="{theme['icon']}"/>''' if icon else ""
            row_svgs.append(f'''
      <g transform="translate(25,{y})" opacity="0">
        <animate attributeName="opacity" from="0" to="1" begin="{delay:.2f}s" dur="0.5s" fill="freeze"/>
        <animateTransform attributeName="transform" type="translate"
                           from="10,{y}" to="25,{y}" begin="{delay:.2f}s" dur="0.5s" fill="freeze"/>
        <g transform="translate(0,-7) scale(0.85)">{icon_svg}</g>
        <text x="24" y="0" font-size="14" fill="{theme['muted']}">{esc(label)}:</text>
        <text x="300" y="0" font-size="14" font-weight="700" fill="{theme['text']}">{value:,}</text>
      </g>''')

        circumference = 2 * 3.14159265 * 40
        total = max(stats.stars + stats.commits * 2 + stats.prs * 3, 1)
        strength = min(total / 3000, 1.0)
        offset = circumference * (1 - strength)
        rank = "A+" if strength > 0.85 else "A" if strength > 0.6 else "B+" if strength > 0.35 else "B"
        rank_svg = f'''
      <g transform="translate(400,97)" opacity="0">
        <animate attributeName="opacity" from="0" to="1" begin="0.6s" dur="0.4s" fill="freeze"/>
        <circle r="40" fill="none" stroke="{theme['track']}" stroke-width="7"/>
        <circle r="40" fill="none" stroke="{theme['icon']}" stroke-width="6"
                stroke-linecap="round" transform="rotate(-90)"
                stroke-dasharray="{circumference:.1f}"
                stroke-dashoffset="{circumference:.1f}">
          <animate attributeName="stroke-dashoffset"
                   from="{circumference:.1f}" to="{offset:.1f}"
                   begin="0.9s" dur="1.2s" fill="freeze"
                   calcMode="spline" keySplines="0.4 0 0.2 1"/>
        </circle>
        <text text-anchor="middle" y="-2" font-size="20" font-weight="700" fill="{theme['title']}" opacity="0">
          {rank}
          <animate attributeName="opacity" from="0" to="1" begin="2.0s" dur="0.4s" fill="freeze"/>
        </text>
        <text text-anchor="middle" y="16" font-size="9" fill="{theme['muted']}" opacity="0">
          RANK
          <animate attributeName="opacity" from="0" to="1" begin="2.2s" dur="0.4s" fill="freeze"/>
        </text>
      </g>'''

    divider = f'  <line x1="25" y1="42" x2="{W-25}" y2="42" stroke="{theme["track"]}" stroke-width="0.5"/>' if layout != "compact" else ""

    return f'''<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{esc(stats.username)}'s GitHub stats">
  <rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="14" fill="{theme['bg']}"
        stroke="{border_stroke}" stroke-width="1"/>
  <text x="25" y="30" font-size="17" font-weight="600" fill="{theme['title']}">
    {esc(stats.username)}'s GitHub Stats
    <animate attributeName="opacity" from="0" to="1" dur="0.6s" fill="freeze"/>
  </text>
  {divider}
  {''.join(row_svgs)}
  {rank_svg}
</svg>'''


def render_languages_svg(stats: Stats, theme: dict, hide_border: bool, layout: str = "compact") -> str:
    total_bytes = sum(stats.languages.values()) or 1
    top = sorted(stats.languages.items(), key=lambda kv: kv[1], reverse=True)[:6]
    if not top:
        top = [("No data", 1)]
        total_bytes = 1

    def color_for(name: str, i: int) -> str:
        return LANGUAGE_COLORS.get(name, FALLBACK_COLORS[i % len(FALLBACK_COLORS)])

    border_stroke = "none" if hide_border else theme["border"]

    if layout == "compact":
        W = 504
        legend_rows = max((len(top) + 1) // 2, 1)
        H = max(205, 82 + (legend_rows - 1) * 36 + 51)

        segs = []
        x_cursor = 0.0
        for i, (name, nbytes) in enumerate(top):
            w = (W - 40) * nbytes / total_bytes
            segs.append(f'<rect x="{20 + x_cursor:.1f}" y="52" width="{w:.1f}" '
                        f'height="7" fill="{color_for(name, i)}"/>')
            x_cursor += w

        legend = []
        for i, (name, nbytes) in enumerate(top):
            row, col = divmod(i, 2)
            cx = 26 if col == 0 else 258
            label_x = 36 if col == 0 else 268
            pct_x = 240 if col == 0 else 472
            cy = 82 + row * 36
            pct = 100 * nbytes / total_bytes
            legend.append(f'''
      <circle cx="{cx}" cy="{cy}" r="5" fill="{color_for(name, i)}"/>
      <text x="{label_x}" y="{cy + 4}" class="label">{esc(name)}</text>
      <text x="{pct_x}" y="{cy + 4}" class="sub" text-anchor="end">{pct:.1f}%</text>''')

        body = f'''
  <line x1="20" y1="42" x2="{W - 20}" y2="42" stroke="{theme['track']}" stroke-width="0.5"/>
  <rect x="20" y="52" width="{W - 40}" height="7" rx="3" fill="{theme['track']}"/>
  {''.join(segs)}
  {''.join(legend)}'''

        return f'''<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{esc(stats.username)}'s most used languages">
  <style>
    text {{ font-family: "Segoe UI", Ubuntu, sans-serif; }}
    .title {{ font-size: 14px; font-weight: 700; fill: {theme['title']}; }}
    .label {{ font-size: 12px; fill: {theme['muted']}; }}
    .sub   {{ font-size: 11px; fill: {theme['text']}; }}
  </style>
  <rect width="{W}" height="{H}" rx="12" fill="{theme['bg']}"/>
  <rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="11" fill="{theme['bg']}"
        stroke="{theme['track']}" stroke-width="1"/>
  <text x="20" y="32" class="title">
    Top Languages
    <animate attributeName="opacity" from="0" to="1" dur="0.6s" fill="freeze"/>
  </text>
  {body}
</svg>'''
    else:
        W = 340
        H = 45 + 20 * len(top)
        rows = []
        for i, (name, nbytes) in enumerate(top):
            pct = 100 * nbytes / total_bytes
            y = 45 + i * 20
            delay = 0.12 * i
            bar_w = (W - 130)
            rows.append(f'''
      <g transform="translate(20,{y})" opacity="0">
        <animate attributeName="opacity" from="0" to="1" begin="{delay:.2f}s" dur="0.5s" fill="freeze"/>
        <circle cx="4" cy="-4" r="4" fill="{color_for(name,i)}"/>
        <text x="14" y="0" font-size="12" fill="{theme['muted']}">{esc(name)}</text>
        <rect x="120" y="-9" width="{bar_w}" height="7" rx="3.5" fill="{theme['track']}"/>
        <rect x="120" y="-9" width="0" height="7" rx="3.5" fill="{color_for(name,i)}">
          <animate attributeName="width" from="0" to="{bar_w*pct/100:.1f}" begin="{delay+0.1:.2f}s"
                   dur="0.9s" fill="freeze" calcMode="spline" keySplines="0.4 0 0.2 1"/>
        </rect>
        <text x="{120+bar_w+8}" y="0" font-size="11" font-weight="700" fill="{theme['text']}">{pct:.1f}%</text>
      </g>''')
        body = ''.join(rows)

    return f'''<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{esc(stats.username)}'s most used languages">
  <rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="14" fill="{theme['bg']}"
        stroke="{border_stroke}" stroke-width="1"/>
  <text x="20" y="28" font-size="16" font-weight="600" fill="{theme['title']}">
    Most Used Languages
    <animate attributeName="opacity" from="0" to="1" dur="0.6s" fill="freeze"/>
  </text>
  {body}
</svg>'''


def render_graph_svg(daily: list[tuple[datetime.date, int]], theme: dict, hide_border: bool) -> str:
    """A glowing line chart of daily contribution activity, matching the
    'Contribution Activity' card style: dark card, blue title, a bright
    animated line with a soft glow, faint gridlines, and month labels."""
    W, H = 495, 180
    pad_l, pad_r, pad_top, pad_bottom = 25, 20, 45, 30
    plot_w = W - pad_l - pad_r
    plot_h = H - pad_top - pad_bottom
    border_stroke = "none" if hide_border else theme["border"]

    if not daily:
        daily = [(datetime.date.today(), 0)]
    counts = [c for _, c in daily]
    max_c = max(counts) or 1
    n = len(daily)

    def x_at(i: int) -> float:
        return pad_l + (i / max(n - 1, 1)) * plot_w

    def y_at(c: int) -> float:
        return pad_top + plot_h - (c / max_c) * plot_h

    points = [(x_at(i), y_at(c)) for i, (_, c) in enumerate(daily)]
    path_d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in points)

    # Month labels: one at the first day-of-month occurrence in range.
    seen_months = set()
    labels = []
    for i, (d, _) in enumerate(daily):
        key = (d.year, d.month)
        if key not in seen_months:
            seen_months.add(key)
            labels.append((x_at(i), d.strftime("%b")))
    label_svgs = "".join(
        f'<text x="{x:.1f}" y="{H-10}" font-size="11" fill="{theme["muted"]}" text-anchor="middle">{m}</text>'
        for x, m in labels
    )

    gridlines = "".join(
        f'<line x1="{pad_l}" y1="{pad_top + plot_h*frac:.1f}" x2="{W-pad_r}" y2="{pad_top + plot_h*frac:.1f}" '
        f'stroke="{theme["track"]}" stroke-width="1" stroke-dasharray="2,4" opacity="0.6"/>'
        for frac in (0.0, 0.5, 1.0)
    )

    peak_i = max(range(n), key=lambda i: counts[i])
    peak_x, peak_y = points[peak_i]
    baseline = pad_top + plot_h
    line_color = shade(theme["title"], 0.72)

    area_d = (
        path_d
        + f" L {points[-1][0]:.1f},{baseline:.1f}"
        + f" L {points[0][0]:.1f},{baseline:.1f} Z"
    )

    return f'''<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Contribution activity">
  <defs>
    <filter id="lineGlow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="2" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
    <linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{line_color}" stop-opacity="0.45"/>
      <stop offset="1" stop-color="{theme['bg']}" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="14" fill="{theme['bg']}"
        stroke="{border_stroke}" stroke-width="1"/>
  <text x="25" y="30" font-size="17" font-weight="600" fill="{theme['title']}">
    Contribution Activity
    <animate attributeName="opacity" from="0" to="1" dur="0.6s" fill="freeze"/>
  </text>
  <g opacity="0">
    <animate attributeName="opacity" from="0" to="1" begin="0.1s" dur="0.5s" fill="freeze"/>
    {gridlines}
  </g>
  <path d="{area_d}" fill="url(#areaFill)" stroke="none" opacity="0">
    <animate attributeName="opacity" from="0" to="1" begin="1.7s" dur="0.9s" fill="freeze"/>
  </path>
  <path id="linePath" d="{path_d}" fill="none" stroke="{line_color}" stroke-width="2.5"
        stroke-linecap="round" stroke-linejoin="round"
        pathLength="1000" stroke-dasharray="1000" stroke-dashoffset="1000">
    <animate attributeName="stroke-dashoffset" from="1000" to="0"
             begin="0.1s" dur="1.6s" fill="freeze" calcMode="spline" keySplines="0.3 0 0.2 1"/>
  </path>
  <path d="{path_d}" fill="none" stroke="{theme['title']}" stroke-width="3.5"
        stroke-linecap="round" stroke-linejoin="round" filter="url(#lineGlow)"
        pathLength="1000" stroke-dasharray="120 880" stroke-dashoffset="1000" opacity="0">
    <animate attributeName="opacity" from="0" to="0.9" begin="2.0s" dur="0.4s" fill="freeze"/>
    <animate attributeName="stroke-dashoffset" from="1000" to="0"
             begin="2.0s" dur="4s" repeatCount="indefinite" calcMode="linear"/>
  </path>
  <circle r="3" fill="{theme['title']}" filter="url(#lineGlow)">
    <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.08;0.88;1"
             begin="0.1s" dur="1.7s" fill="freeze"/>
    <animateMotion dur="1.6s" begin="0.1s" fill="freeze"
                   calcMode="spline" keySplines="0.3 0 0.2 1">
      <mpath href="#linePath"/>
    </animateMotion>
  </circle>
  <circle cx="{peak_x:.1f}" cy="{peak_y:.1f}" r="0" fill="{theme['title']}"
          stroke="{theme['bg']}" stroke-width="2" filter="url(#lineGlow)">
    <animate attributeName="r" from="0" to="4.5" begin="1.7s" dur="0.4s" fill="freeze"/>
    <animate attributeName="r" values="4.5;6;4.5" begin="2.1s" dur="1.8s" repeatCount="indefinite"/>
  </circle>
  <g opacity="0">
    <animate attributeName="opacity" from="0" to="1" begin="1.7s" dur="0.5s" fill="freeze"/>
    {label_svgs}
  </g>
</svg>'''


# --------------------------------------------------------------------------
# CI entry point - env-var driven, no CLI args
# --------------------------------------------------------------------------

def env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() not in ("false", "0", "no")


def infer_username() -> str:
    override = os.environ.get("GH_USERNAME")
    if override:
        return override
    repo = os.environ.get("GITHUB_REPOSITORY")  # "owner/repo", set automatically in Actions
    if repo and "/" in repo:
        return repo.split("/")[0]
    print("[error] could not determine username: set GH_USERNAME or run inside "
          "GitHub Actions (GITHUB_REPOSITORY).", file=sys.stderr)
    sys.exit(1)


def main():
    username = infer_username()
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    theme = theme_or_default(os.environ.get("STATS_THEME", "tokyonight"))
    hide_border = env_bool("HIDE_BORDER", True)
    include_all_commits = env_bool("INCLUDE_ALL_COMMITS", True)
    output_dir = os.environ.get("OUTPUT_DIR", "assets")

    if not token:
        print("[warn] no GH_TOKEN/GITHUB_TOKEN found - API calls will be limited "
              "to 60/hr and may fail.", file=sys.stderr)

    print(f"Fetching GitHub data for {username}...")
    stats = fetch_stats(username, token, include_all_commits)

    print(f"Fetching contribution activity for {username}...")
    daily = fetch_contribution_calendar(username, token)

    os.makedirs(output_dir, exist_ok=True)

    outputs = [
        ("stats.svg", render_stats_svg(stats, theme, hide_border, layout="normal")),
        ("lang.svg", render_languages_svg(stats, theme, hide_border, layout="compact")),
        ("graph.svg", render_graph_svg(daily, theme, hide_border)),
    ]

    for filename, svg in outputs:
        path = os.path.join(output_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()