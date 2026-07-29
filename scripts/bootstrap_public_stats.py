#!/usr/bin/env python3
"""Create the first stat SVGs from GitHub's public HTML and REST API.

The scheduled workflow uses the authenticated GraphQL generator, which has
exact language-byte totals. This bootstrap exists so a freshly cloned profile
can render before the first workflow run without requiring a local token.
"""

import json
import re
import urllib.request
from datetime import date, timedelta

import generate_stats


LOGIN = "webobscure"


def request(url):
    req = urllib.request.Request(url, headers={"User-Agent": f"{LOGIN}-profile-bootstrap"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def contribution_weeks(markup):
    cell = re.compile(
        r'data-date="(?P<date>\d{4}-\d{2}-\d{2})"[^>]*'
        r'id="(?P<id>contribution-day-component-[^"]+)"[^>]*></td>\s*'
        r'<tool-tip[^>]*for="(?P=id)"[^>]*>(?P<label>[^<]+)</tool-tip>',
        re.DOTALL,
    )
    days = []
    for match in cell.finditer(markup):
        day = date.fromisoformat(match.group("date"))
        count_match = re.match(r"([\d,]+) contributions?", match.group("label"))
        count = int(count_match.group(1).replace(",", "")) if count_match else 0
        weekday = day.isoweekday() % 7
        days.append(
            {
                "date": day.isoformat(),
                "contributionCount": count,
                "weekday": weekday,
                "week": (day - timedelta(days=weekday)).isoformat(),
            }
        )

    # Match generate_stats.window(): exactly 365 whole UTC days. GitHub's
    # public calendar includes whole edge weeks and can expose a few extras.
    last_day = max(date.fromisoformat(day["date"]) for day in days)
    first_day = last_day - timedelta(days=364)
    days = [day for day in days if date.fromisoformat(day["date"]) >= first_day]

    grouped = {}
    for day in days:
        grouped.setdefault(day.pop("week"), []).append(day)
    return [grouped[key] for key in sorted(grouped)]


def repository_nodes(payload):
    nodes = []
    for repo in payload:
        language = repo.get("language")
        if repo.get("fork") or repo.get("private") or not language:
            continue
        # REST exposes the dominant language but not its byte count in this
        # response. Repository size is a stable bootstrap weight; GraphQL
        # replaces it with exact language bytes on the first scheduled run.
        nodes.append(
            {
                "languages": {
                    "edges": [
                        {
                            "size": max(1, int(repo.get("size") or 1) * 1024),
                            "node": {"name": language},
                        }
                    ]
                }
            }
        )
    return nodes


def main():
    calendar = request(f"https://github.com/users/{LOGIN}/contributions").decode("utf-8")
    repos = json.loads(
        request(
            f"https://api.github.com/users/{LOGIN}/repos?per_page=100&sort=updated"
        )
    )
    weeks = contribution_weeks(calendar)
    total = sum(day["contributionCount"] for week in weeks for day in week)
    user = {
        "contributionsCollection": {
            "contributionCalendar": {
                "totalContributions": total,
                "weeks": [{"contributionDays": week} for week in weeks],
            }
        },
        "repositories": {"nodes": repository_nodes(repos)},
    }

    summary = generate_stats.summarise(user)
    files = {
        "stats.svg": generate_stats.draw_stats(summary),
        "streak.svg": generate_stats.draw_streak(summary),
        "langs.svg": generate_stats.draw_langs(summary),
        "year.svg": generate_stats.draw_year(summary),
    }
    for word in ("about", "stack", "projects", "stats", "about this page"):
        files[f"hd-{word.replace(' ', '-')}.svg"] = generate_stats.draw_heading(word)

    for name, svg in files.items():
        generate_stats.write(name, svg)
    print(f"bootstrapped {total} contributions across {len(weeks)} weeks")


if __name__ == "__main__":
    main()
