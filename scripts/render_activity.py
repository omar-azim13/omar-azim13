#!/usr/bin/env python3
"""Render a GitHub profile activity dashboard from GitHub GraphQL.

No dependencies beyond Python's standard library. No private repository names,
commit messages, or access tokens are written to the output SVG.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape

LOGIN = os.getenv("GH_PROFILE_USER", "omar-azim13")
TOKEN = os.getenv("GH_PROFILE_TOKEN", "")
OUT = Path(__file__).resolve().parent.parent / "assets" / "activity-overview.svg"
QUERY = """
query ProfileActivity($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def fetch_calendar():
    if not TOKEN:
        raise RuntimeError("GH_PROFILE_TOKEN is missing. Use the GitHub Actions workflow.")
    now = datetime.now(timezone.utc)
    # UTC day boundaries are consistent with GitHub's GraphQL response.
    first = date.today() - timedelta(days=364)
    frm = datetime(first.year, first.month, first.day, tzinfo=timezone.utc)
    payload = json.dumps({
        "query": QUERY,
        "variables": {
            "login": LOGIN,
            "from": frm.isoformat().replace("+00:00", "Z"),
            "to": now.isoformat().replace("+00:00", "Z"),
        },
    }).encode("utf-8")
    req = Request("https://api.github.com/graphql", data=payload, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "omar-profile-activity-svg",
        "X-GitHub-Api-Version": "2022-11-28",
    }, method="POST")
    try:
        with urlopen(req, timeout=25) as response:
            result = json.load(response)
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"GitHub GraphQL request failed: {exc}") from exc
    if result.get("errors"):
        raise RuntimeError(f"GitHub GraphQL error: {result['errors']}")
    user = (result.get("data") or {}).get("user")
    if user is None:
        raise RuntimeError(f"GitHub user {LOGIN!r} was not found")
    coll = user["contributionsCollection"]
    cal = coll["contributionCalendar"]
    days = {}
    for week in cal["weeks"]:
        for day in week["contributionDays"]:
            days[date.fromisoformat(day["date"])] = day["contributionCount"]
    return {
        "total": cal["totalContributions"],
        "restricted": coll["restrictedContributionsCount"],
        "days": days,
        "first": first,
        "today": now.date(),
    }


def streaks(days, today):
    """GitHub current streak allows a grace day if there was no activity today."""
    counts = {d: int(n) for d, n in days.items()}
    active = [d for d, n in counts.items() if n > 0]
    longest, running = 0, 0
    for d in sorted(counts):
        running = running + 1 if counts[d] > 0 else 0
        longest = max(longest, running)
    end = today if counts.get(today, 0) else today - timedelta(days=1)
    cur = 0
    while counts.get(end, 0) > 0:
        cur += 1
        end -= timedelta(days=1)
    return len(active), cur, longest


def render(metrics):
    days = metrics["days"]
    total = metrics["total"]
    restricted = metrics.get("restricted", 0)
    first, today = metrics["first"], metrics["today"]
    active_days, current, longest = streaks(days, today)

    # A 53-week heatmap, aligned to Sunday through Saturday.
    start = first - timedelta(days=(first.weekday() + 1) % 7)
    end = today + timedelta(days=(5 - today.weekday()) % 7)
    weeks = (end - start).days // 7 + 1
    # 54 columns can occur for a rolling 365-day calendar; fit dynamically.
    plot_x, plot_y, plot_w, gap = 83, 259, 944, 4
    sq = min(14, (plot_w - (weeks - 1) * gap) / weeks)
    step = sq + gap
    elems = []
    def add(s):
        elems.append(s)
    def text(x, y, label, size=16, fill="#c9d1d9", weight="normal", anchor="start"):
        add(f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif">{escape(str(label))}</text>')

    add('<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="435" viewBox="0 0 1100 435" role="img" aria-label="GitHub contributions and streaks">')
    add('<rect width="1100" height="435" rx="14" fill="#0d1117"/>')
    add('<rect x="1" y="1" width="1098" height="433" rx="13" fill="none" stroke="#30363d" stroke-width="2"/>')
    text(36, 48, "activity / past 365 days", 21, "#e6edf3", "600")
    text(1063, 46, f"updated {today:%d %b %Y} (UTC)", 14, "#8b949e", anchor="end")

    stat_values = [
        (f"{total:,}", "contributions"),
        (f"{active_days:,}", "active days"),
        (str(current), "current streak"),
        (str(longest), "longest streak"),
    ]
    for idx, (num, label) in enumerate(stat_values):
        x = 36 + idx * 261
        add(f'<rect x="{x}" y="69" width="248" height="112" rx="10" fill="#111820" stroke="#30363d"/>')
        text(x+22, 122, num, 38, "#e6edf3", "600")
        text(x+22, 157, label, 16, "#a9b4c2")
    add('<line x1="36" x2="1064" y1="213" y2="213" stroke="#30363d"/>')
    text(36, 243, "contribution calendar", 16, "#a9b4c2", "500")

    for label, weekday in [("Mon", 1), ("Wed", 3), ("Fri", 5)]:
        text(36, round(plot_y+weekday*step + sq*.78, 2), label, 13, "#8b949e")
    # No fabricated data: use the actual contributionCount for each day.
    for w in range(weeks):
        for dow in range(7):
            d = start + timedelta(days=7*w+dow)
            if not first <= d <= today:
                color = "#090d12"
            else:
                count = int(days.get(d, 0))
                color = (
                    "#161b22" if count == 0 else
                    "#3b4552" if count <= 2 else
                    "#637081" if count <= 5 else
                    "#a3adba" if count <= 10 else "#e6edf3"
                )
            x = plot_x+w*step
            y = plot_y+dow*step
            add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{sq:.1f}" height="{sq:.1f}" rx="2.5" fill="{color}"/>')

    months = set()
    for w in range(weeks):
        day = start + timedelta(days=7*w)
        key = (day.year,day.month)
        if day.day <= 7 and key not in months:
            x = plot_x+w*step
            text(f"{x:.1f}", 254, day.strftime("%b"), 12, "#7e8997")
            months.add(key)
    source_caption = ("Includes anonymized private contributions" if restricted > 0
                      else "Public contributions only / verify private activity settings")
    text(36, 414, f"GitHub GraphQL / {source_caption}", 13, "#8b949e")
    text(1062, 414, "less  ▪ ▪ ▪ ▪ ▪  more", 13, "#a9b4c2", anchor="end")
    add('</svg>')
    return "\n".join(elems) + "\n"


def main():
    metric = fetch_calendar()
    # Avoid silently publishing a graph if GitHub returned an empty response.
    if not metric["days"]:
        raise RuntimeError("GitHub returned no contribution calendar days")
    svg = render(metric)
    OUT.write_text(svg, encoding="utf-8")
    print(f"Saved {OUT}: {metric['total']} total contributions, "
          f"{metric['restricted']} restricted/anonymized contributions")
    if metric["total"] < 100 and metric["restricted"] == 0:
        print("NOTE: If GitHub profile shows many more contributions, the token "
              "may lack read:user, or private contributions are not shared.")

if __name__ == "__main__":
    main()
