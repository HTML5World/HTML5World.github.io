#!/usr/bin/env python3
"""Discover published HTML5 World games without per-game manifest files.

A public repository is included when GitHub Pages is enabled and its Pages
source contains an index.html file. Metadata is inferred from the repository
name, description, topics, and optional image files beside index.html.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

OWNER = os.environ.get("GITHUB_OWNER", "HTML5World").strip()
MAIN_REPOSITORY = os.environ.get("MAIN_REPOSITORY", "HTML5World.github.io").strip()
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
PAGES_TOKEN = os.environ.get("PAGES_ENABLE_TOKEN", "")
OUTPUT = os.environ.get("CATALOG_OUTPUT", "games.json")
API_ROOT = "https://api.github.com"
USER_AGENT = "HTML5-World-Automatic-Game-Discovery"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".svg"}
THUMBNAIL_NAMES = (
    "thumbnail", "cover", "banner", "preview", "screenshot", "poster",
    "og-image", "social-preview", "logo", "icon",
)

CATEGORY_TERMS = {
    "Action": (
        "action", "shooter", "fps", "battle", "combat", "war", "zombie",
        "fighting", "survival", "gunfight",
    ),
    "Racing": (
        "racing", "race", "racer", "driving", "car", "cars", "kart",
        "drift", "motorcycle", "bike", "moto",
    ),
    "Puzzle": (
        "puzzle", "2048", "sudoku", "tetris", "chess", "mahjong", "logic",
        "wordle", "word-game", "crossword", "memory",
    ),
    "Sports": (
        "sports", "sport", "football", "soccer", "basketball", "cricket",
        "tennis", "golf", "baseball", "pool", "bowling",
    ),
    "Adventure": (
        "adventure", "quest", "exploration", "platformer", "platform",
        "story", "rpg", "role-playing",
    ),
    "Arcade": (
        "arcade", "runner", "snake", "flappy", "bubble", "clicker", "idle",
        "brick-breaker", "shoot-em-up",
    ),
}


def request_json(url: str, *, allow_404: bool = False) -> Any | None:
    base_headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }

    def fetch(headers: dict[str, str]) -> Any:
        request = Request(url, headers=headers)
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    headers = dict(base_headers)
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    try:
        return fetch(headers)
    except HTTPError as exc:
        # The workflow token belongs to the portal repository. If GitHub does
        # not allow that token to read another public repository, retry the
        # public endpoint without authentication rather than treating it as
        # missing. This also keeps discovery working without extra PAT secrets.
        if TOKEN and exc.code in (401, 403, 404):
            message = exc.read().lower()
            if exc.code != 403 or b"rate limit" not in message:
                try:
                    return fetch(base_headers)
                except HTTPError as public_error:
                    if allow_404 and public_error.code == 404:
                        return None
                    if public_error.code not in (401, 403, 404):
                        raise
                    if public_error.code == 404:
                        raise exc
                    exc = public_error
        if allow_404 and exc.code == 404:
            return None
        if exc.code == 403:
            remaining = exc.headers.get("X-RateLimit-Remaining", "unknown")
            reset = exc.headers.get("X-RateLimit-Reset", "unknown")
            raise RuntimeError(
                f"GitHub API returned 403 (rate limit remaining: {remaining}, reset: {reset})."
            ) from exc
        raise


def _list_repositories_from(endpoint: str) -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    page = 1
    while True:
        query = {
            "type": "public" if endpoint == "orgs" else "owner",
            "sort": "updated",
            "direction": "desc",
            "per_page": 100,
            "page": page,
        }
        url = f"{API_ROOT}/{endpoint}/{quote(OWNER, safe='')}/repos?{urlencode(query)}"
        batch = request_json(url)
        if not isinstance(batch, list):
            raise RuntimeError("GitHub returned an unexpected repository-list response.")
        repositories.extend(repo for repo in batch if isinstance(repo, dict))
        if len(batch) < 100:
            break
        page += 1
        time.sleep(0.12)
    return repositories


def list_repositories() -> list[dict[str, Any]]:
    """Support both GitHub organizations and personal user accounts."""
    try:
        repositories = _list_repositories_from("orgs")
        print(f"Found GitHub organization: {OWNER}")
        return repositories
    except HTTPError as exc:
        if exc.code != 404:
            raise RuntimeError(
                f"Could not list public repositories for organization {OWNER}: HTTP {exc.code}."
            ) from exc
        print(f"{OWNER} is not an organization endpoint; checking the user account.")

    try:
        repositories = _list_repositories_from("users")
        print(f"Found GitHub user account: {OWNER}")
        return repositories
    except HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(
                f"GitHub returned 404 for both /orgs/{OWNER}/repos and "
                f"/users/{OWNER}/repos. Check GITHUB_OWNER; it must be the exact "
                "public GitHub organization or username."
            ) from exc
        raise RuntimeError(
            f"Could not list public repositories for {OWNER}: HTTP {exc.code}."
        ) from exc


def _directory_contents(repo_name: str, branch: str, path: str) -> list[dict[str, Any]] | None:
    api_path = quote(path.strip("/"), safe="/")
    endpoint = f"{API_ROOT}/repos/{quote(OWNER, safe='')}/{quote(repo_name, safe='')}/contents"
    if api_path:
        endpoint += f"/{api_path}"
    endpoint += "?" + urlencode({"ref": branch})
    result = request_json(endpoint, allow_404=True)
    if not isinstance(result, list):
        return None
    return [item for item in result if isinstance(item, dict)]


def _has_index(contents: list[dict[str, Any]] | None) -> bool:
    return bool(contents and any(
        item.get("type") == "file" and str(item.get("name", "")).lower() == "index.html"
        for item in contents
    ))


def find_pages_entry(repo: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]], dict[str, Any]] | None:
    """Return (branch, directory, contents, Pages metadata) for a site entrypoint."""
    repo_name = str(repo.get("name") or "")
    if not repo_name or not repo.get("has_pages"):
        return None

    pages_info: dict[str, Any] = {}
    pages_url = f"{API_ROOT}/repos/{quote(OWNER, safe='')}/{quote(repo_name, safe='')}/pages"
    try:
        response = request_json(pages_url, allow_404=True)
        if isinstance(response, dict):
            pages_info = response
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"Pages metadata unavailable for {repo_name}: {exc}", file=sys.stderr)

    source = pages_info.get("source") if isinstance(pages_info.get("source"), dict) else {}
    preferred_branch = source.get("branch") or repo.get("default_branch") or "main"
    preferred_path = str(source.get("path") or "/").strip("/")

    candidates: list[tuple[str, str]] = []
    for branch, path in (
        (preferred_branch, preferred_path),
        (repo.get("default_branch") or "main", ""),
        (repo.get("default_branch") or "main", "docs"),
        ("gh-pages", ""),
        ("gh-pages", "docs"),
    ):
        item = (str(branch), str(path))
        if item not in candidates:
            candidates.append(item)

    for branch, path in candidates:
        contents = _directory_contents(repo_name, branch, path)
        if _has_index(contents):
            return branch, path, contents or [], pages_info

    return None



def enable_github_pages(repo_name: str, branch: str, directory: str) -> dict[str, Any]:
    """Enable Pages for a discovered public game repository using a PAT."""
    if not PAGES_TOKEN:
        raise RuntimeError(
            "GitHub Pages is disabled and PAGES_ENABLE_TOKEN is not configured. "
            "Add a fine-grained PAT with Pages: write access as the "
            "PAGES_ENABLE_TOKEN Actions secret."
        )

    url = f"{API_ROOT}/repos/{quote(OWNER, safe='')}/{quote(repo_name, safe='')}/pages"
    payload = json.dumps({
        "source": {"branch": branch, "path": "/" + directory.strip("/") if directory else "/"}
    }).encode("utf-8")
    request = Request(
        url, data=payload, method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {PAGES_TOKEN}",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            print(f"Enabled GitHub Pages: {repo_name} ({branch}:{directory or '/'})")
            return result if isinstance(result, dict) else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        if exc.code == 409:
            # Another run may have enabled Pages between the check and POST.
            existing = request_json(url, allow_404=True)
            if isinstance(existing, dict):
                return existing
        raise RuntimeError(
            f"Could not enable GitHub Pages for {repo_name}: HTTP {exc.code}: {detail}"
        ) from exc


def find_game_source(repo: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]] | None:
    """Find an index.html even when GitHub Pages has not been enabled yet."""
    branch = str(repo.get("default_branch") or "main")
    for candidate_branch, directory in (
        (branch, ""), (branch, "docs"), ("gh-pages", ""), ("gh-pages", "docs")
    ):
        contents = _directory_contents(str(repo["name"]), candidate_branch, directory)
        if _has_index(contents):
            return candidate_branch, directory, contents or []
    return None

def _raw_url(repo_name: str, branch: str, directory: str, filename: str) -> str:
    pieces = [OWNER, repo_name, branch]
    if directory:
        pieces.append(directory.strip("/"))
    pieces.append(filename)
    return "https://raw.githubusercontent.com/" + "/".join(
        quote(piece, safe="") for piece in pieces
    )


def detect_thumbnail(
    repo: dict[str, Any], branch: str, directory: str, contents: list[dict[str, Any]]
) -> str:
    files = {
        str(item.get("name", "")).lower(): item
        for item in contents
        if item.get("type") == "file"
    }

    for wanted in THUMBNAIL_NAMES:
        for filename, item in files.items():
            stem, extension = os.path.splitext(filename)
            if stem == wanted and extension in IMAGE_EXTENSIONS:
                return _raw_url(str(repo["name"]), branch, directory, str(item["name"]))

    # Prefer a repository social preview only when no local game artwork exists.
    preview = repo.get("open_graph_image_url")
    if isinstance(preview, str) and preview.startswith("https://"):
        return preview
    return ""


def _slug_words(value: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return [part for part in re.split(r"[^a-zA-Z0-9]+", spaced.lower()) if part]


def make_title(repo_name: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", repo_name)
    words = re.sub(r"[-_]+", " ", words).strip()
    return " ".join(word if word.isdigit() else word.capitalize() for word in words.split())


def detect_category(repo: dict[str, Any]) -> str:
    topics = repo.get("topics") if isinstance(repo.get("topics"), list) else []
    text = " ".join([
        str(repo.get("name") or ""),
        str(repo.get("description") or ""),
        " ".join(str(topic) for topic in topics),
    ]).lower()
    words = set(_slug_words(text))

    for category in ("Puzzle", "Racing", "Sports", "Action", "Adventure", "Arcade"):
        terms = CATEGORY_TERMS[category]
        for term in terms:
            if "-" in term:
                if term in text:
                    return category
            elif term in words:
                return category
    return "Arcade"


def make_game(
    repo: dict[str, Any], branch: str, directory: str,
    contents: list[dict[str, Any]], pages_info: dict[str, Any],
) -> dict[str, Any]:
    repo_name = str(repo["name"])
    name = make_title(repo_name)
    description = str(repo.get("description") or "Play this free browser game instantly in your browser.").strip()
    category = detect_category(repo)
    thumbnail = detect_thumbnail(repo, branch, directory, contents)

    game_url = pages_info.get("html_url")
    if not isinstance(game_url, str) or not game_url.startswith(("https://", "http://")):
        game_url = f"https://{OWNER.lower()}.github.io/{quote(repo_name, safe='')}/"

    topics = repo.get("topics") if isinstance(repo.get("topics"), list) else []
    tags = [str(topic) for topic in topics if isinstance(topic, str)]
    tags.extend(word for word in _slug_words(repo_name) if word not in tags)

    return {
        "id": repo_name,
        "name": name,
        "description": description,
        "category": category,
        "thumbnail": thumbnail,
        "url": game_url,
        "featured": False,
        "tags": list(dict.fromkeys(tags))[:12],
        "updated": str(repo.get("updated_at") or ""),
        "homepage": str(repo.get("html_url") or f"https://github.com/{OWNER}/{repo_name}"),
        "orientation": "landscape",
    }


def discover_games(repositories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    skipped = 0

    for repo in repositories:
        name = str(repo.get("name") or "")
        if (
            not name
            or name.lower() == MAIN_REPOSITORY.lower()
            or repo.get("fork")
            or repo.get("archived")
            or repo.get("disabled")
            or repo.get("private")
        ):
            continue

        try:
            if repo.get("has_pages"):
                entry = find_pages_entry(repo)
                if not entry:
                    skipped += 1
                    continue
                branch, directory, contents, pages_info = entry
            else:
                source = find_game_source(repo)
                if not source:
                    continue
                branch, directory, contents = source
                pages_info = enable_github_pages(name, branch, directory)
            game = make_game(repo, branch, directory, contents, pages_info)
            games.append(game)
            print(f"Discovered: {name} ({branch}:{directory or '/'})")
        except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
            skipped += 1
            print(f"Warning: skipped {name}: {exc}", file=sys.stderr)

    games.sort(key=lambda game: game["updated"], reverse=True)
    # The four most recently updated games fill the featured shelf automatically.
    for game in games[:4]:
        game["featured"] = True
    return games


def main() -> None:
    if not OWNER:
        raise RuntimeError("GITHUB_OWNER is empty.")

    repositories = list_repositories()
    games = discover_games(repositories)

    os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as file:
        json.dump(games, file, ensure_ascii=False, indent=2)
        file.write("\n")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"Generated {OUTPUT}: {len(games)} game(s) discovered. {stamp}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # Fail clearly and preserve the previously committed catalog.
        print(f"Game discovery failed: {error}", file=sys.stderr)
        raise
