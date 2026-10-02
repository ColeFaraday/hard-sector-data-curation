"""The parts that need the network: new HEPData versions, archives and INSPIRE keys.

Nothing else in hsdc touches the network, so a build is reproducible offline. Every
function takes the function that does the fetching, so tests can replace it.
"""

from __future__ import annotations

import io
import json
import re
import tarfile
import urllib.request
from pathlib import Path
from typing import Any, Callable

HEPDATA = "https://www.hepdata.net"
INSPIRE = "https://inspirehep.net/api/literature"

Fetch = Callable[[str], bytes]


class UpdateError(RuntimeError):
    """The network answered something this code does not understand."""


def fetch_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "hsdc (hard-sector curation)"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def latest_version(inspire_id: int, fetch: Fetch | None = None) -> int:
    """The newest version of a record on HEPData."""
    fetch = fetch or fetch_url
    url = f"{HEPDATA}/record/ins{inspire_id}?format=json"
    try:
        data = json.loads(fetch(url))
    except ValueError as exc:
        raise UpdateError(f"{url} did not answer JSON: {exc}") from None
    for holder in (data, data.get("record") if isinstance(data, dict) else None):
        if isinstance(holder, dict):
            for key in ("version", "latest_version"):
                if isinstance(holder.get(key), int):
                    return holder[key]
    raise UpdateError(
        f"{url} gave no version number (keys: {sorted(data) if isinstance(data, dict) else type(data)})"
        "; HEPData's answer changed, so hsdc/updates.py needs updating"
    )


def download_record(
    inspire_id: int, version: int, parent: str | Path, fetch: Fetch | None = None
) -> Path:
    """Unpack ``HEPData-ins<id>-v<version>-yaml`` into ``parent`` and return its path."""
    fetch = fetch or fetch_url
    parent = Path(parent)
    name = f"HEPData-ins{inspire_id}-v{version}-yaml"
    target = parent / name
    if target.exists():
        raise UpdateError(f"{target} already exists")
    url = f"{HEPDATA}/download/submission/ins{inspire_id}/{version}/yaml"
    payload = fetch(url)
    try:
        archive = tarfile.open(fileobj=io.BytesIO(payload), mode="r:*")
    except tarfile.TarError as exc:
        raise UpdateError(f"{url} did not answer a tar archive: {exc}") from None
    with archive:
        for member in archive.getmembers():
            resolved = (parent / member.name).resolve()
            if not member.isfile() and not member.isdir():
                raise UpdateError(f"{url}: unexpected member {member.name!r} in the archive")
            if parent.resolve() not in resolved.parents and resolved != parent.resolve():
                raise UpdateError(f"{url}: member {member.name!r} would leave {parent}")
        parent.mkdir(parents=True, exist_ok=True)
        # Python 3.12 and later can refuse unsafe members itself; the loop above did too.
        options = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        archive.extractall(parent, **options)
    if not target.is_dir():
        raise UpdateError(f"{url}: the archive did not contain {name}/")
    return target


def inspire_info(inspire_id: int, fetch: Fetch | None = None) -> dict[str, Any]:
    """The texkey and arXiv number INSPIRE has for a record."""
    fetch = fetch or fetch_url
    url = f"{INSPIRE}/{inspire_id}?fields=texkeys,arxiv_eprints,titles"
    try:
        metadata = json.loads(fetch(url))["metadata"]
    except (ValueError, KeyError) as exc:
        raise UpdateError(f"{url} gave an unexpected answer: {exc!r}") from None
    info: dict[str, Any] = {}
    if metadata.get("texkeys"):
        info["texkey"] = metadata["texkeys"][0]
    if metadata.get("arxiv_eprints"):
        info["arxiv"] = metadata["arxiv_eprints"][0]["value"]
    if metadata.get("titles"):
        info["title"] = metadata["titles"][0]["title"]
    return info


_PIN = re.compile(r"(record:\s*\{[^}]*?version:\s*)(\d+)")


def repin(recipe_path: Path, version: int) -> None:
    """Move the version pin in a recipe's one-line ``record:`` entry."""
    text = recipe_path.read_text(encoding="utf-8")
    new, count = _PIN.subn(lambda m: f"{m.group(1)}{version}", text, count=1)
    if count != 1:
        raise UpdateError(
            f"{recipe_path.name}: cannot find a one-line `record: {{ inspire_id: ..., version: ... }}`"
        )
    recipe_path.write_text(new, encoding="utf-8")
