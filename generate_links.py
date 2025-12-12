import sys
import os
import json
import time
import csv
import ssl
from pathlib import Path
from urllib.parse import quote_plus, urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError


def read_lines_with_fallback(path: Path):
    encodings = ["utf-8-sig", "utf-8", "cp1251", "windows-1251", "latin-1"]
    last_err = None
    for enc in encodings:
        try:
            with path.open("r", encoding=enc, errors="strict") as f:
                lines = [ln.strip() for ln in f.readlines()]
            return enc, lines
        except Exception as e:
            last_err = e
            continue
    # Fallback with replacement to avoid crash
    with path.open("r", encoding="utf-8", errors="replace") as f:
        lines = [ln.strip() for ln in f.readlines()]
    return "utf-8(replaced)", lines


def _is_coords(text: str) -> bool:
    import re
    return re.match(r"^\s*[+-]?\d+(?:\.\d+)?\s*,\s*[+-]?\d+(?:\.\d+)?\s*$", text) is not None


def _user_agent(email: str | None = None) -> str:
    base = "addr2yandex/1.1"
    mail = email or os.environ.get("NOMINATIM_EMAIL") or ""
    mail = mail.strip()
    if mail and " " not in mail:
        return f"{base} ({mail})"
    return base


def _get_ssl_context():
    ctx = getattr(_get_ssl_context, "_ctx", None)
    if ctx is None:
        ctx = ssl.create_default_context()
        try:
            import certifi  # type: ignore
        except ImportError:
            pass
        else:
            try:
                ctx.load_verify_locations(certifi.where())
            except Exception:
                # If loading certifi fails, fall back to default roots
                ctx = ssl.create_default_context()
        _get_ssl_context._ctx = ctx
    return ctx


def _fetch_json(url: str, *, headers: dict[str, str] | None = None, timeout: float = 20.0):
    req_headers = {"User-Agent": _user_agent()}
    if headers:
        for k, v in headers.items():
            if v:
                req_headers[k] = v
    req = Request(url, headers=req_headers)
    with urlopen(req, timeout=timeout, context=_get_ssl_context()) as resp:
        return json.load(resp)


try:
    from yandex_api_key import YANDEX_GEOCODER_API_KEY as _YANDEX_KEY_FROM_FILE
except ImportError:
    _YANDEX_KEY_FROM_FILE = ""


DEFAULT_YANDEX_API_KEY = (_YANDEX_KEY_FROM_FILE or os.environ.get("YANDEX_GEOCODER_API_KEY", "")).strip()


_GEOCODE_EXCEPTIONS = (
    HTTPError,
    URLError,
    TimeoutError,
    ValueError,
    json.JSONDecodeError,
    ssl.SSLError,
)


def build_yandex_link(address: str, domain: str = "yandex.ru") -> str:
    # Universal link; opens the app on iOS if installed (via Universal Links)
    base = f"https://{domain}/maps/"
    # rtext: start~end, with empty start means current location
    # mode=routes: explicitly open route builder
    # rtt=masstransit: public transport
    # If target looks like coordinates "lat,lon", keep comma unobscured
    if _is_coords(address):
        target = address.replace(" ", "")
    else:
        target = quote_plus(address)
    return f"{base}?mode=routes&rtext=~{target}&rtt=masstransit"


def _cache_path() -> Path:
    return Path("geocache.json")


def _load_cache() -> dict:
    p = _cache_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    try:
        _cache_path().write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        # Cache write failure should not break the run
        pass


def _yandex_geocode(addr: str, apikey: str, lang: str = "ru_RU") -> tuple[float, float] | None:
    params = {
        "apikey": apikey,
        "geocode": addr,
        "format": "json",
        "results": "1",
        "lang": lang,
    }
    url = "https://geocode-maps.yandex.ru/1.x/?" + urlencode(params)
    data = _fetch_json(
        url,
        headers={
            "User-Agent": _user_agent(),
            "Accept": "application/json",
        },
        timeout=15,
    )
    members = (
        data.get("response", {})
        .get("GeoObjectCollection", {})
        .get("featureMember", [])
    )
    if not members:
        return None
    pos = (
        members[0]
        .get("GeoObject", {})
        .get("Point", {})
        .get("pos")
    )
    if not pos:
        return None
    # Yandex returns "lon lat"
    lon_str, lat_str = pos.split()
    return float(lat_str), float(lon_str)


def _nominatim_geocode(addr: str, lang: str = "ru", email: str | None = None) -> tuple[float, float] | None:
    params = {
        "q": addr,
        "format": "jsonv2",
        "limit": "1",
        "accept-language": lang,
    }
    url = "https://nominatim.openstreetmap.org/search?" + urlencode(params)
    headers = {
        "User-Agent": _user_agent(email),
        "Accept-Language": lang,
        "Accept": "application/json",
    }
    arr = _fetch_json(url, headers=headers, timeout=20)
    if not arr:
        return None
    lat = float(arr[0]["lat"])  # lat
    lon = float(arr[0]["lon"])  # lon
    return lat, lon


def _photon_geocode(addr: str, lang: str = "ru") -> tuple[float, float] | None:
    supported_langs = {"default", "en", "de", "fr"}
    lang_param = lang if lang in supported_langs else "default"
    import re

    def _normalize_variant(text: str) -> str:
        cleaned = " ".join(text.replace(",", " ").split())
        return cleaned.strip()

    def _separate_suffixes(text: str) -> str:
        tmp = re.sub(r"(\d[^\s,]*)\s*([сc])(?=\d)", r"\1 \2", text, flags=re.IGNORECASE)
        tmp = re.sub(r"([сc])\s*(\d+)", r"\1 \2", tmp, flags=re.IGNORECASE)
        tmp = re.sub(r"([кk])\s*(\d+)", r"\1 \2", tmp, flags=re.IGNORECASE)
        tmp = re.sub(r"(стр(?:\.|оение)?)\s*(\d+)", r"стр \2", tmp, flags=re.IGNORECASE)
        return tmp

    def _normalized_house(value: str) -> str:
        return re.sub(r"[^0-9a-zа-я]", "", value.lower())

    base_variant = _normalize_variant(addr)
    variants: list[str] = []

    def _add_variant(text: str):
        norm = _normalize_variant(text)
        if norm and norm not in variants:
            variants.append(norm)

    _add_variant(addr)
    _add_variant(base_variant)
    _add_variant(_separate_suffixes(addr))
    if "," in addr:
        parts = [part.strip() for part in addr.split(",") if part.strip()]
        if len(parts) > 1:
            reordered = " ".join(parts[1:] + [parts[0]])
            _add_variant(reordered)
            _add_variant(_separate_suffixes(reordered))

    headers = {
        "User-Agent": _user_agent(),
        "Accept": "application/json",
    }
    address_lower = base_variant.lower()
    house_tokens = set()
    for token in re.findall(r"\d+[^\s,]*", addr):
        normalized = _normalized_house(token)
        if normalized:
            house_tokens.add(normalized)

    best_coords: tuple[float, float] | None = None
    best_score = -1.0
    for variant in variants:
        params = {
            "q": variant,
            "limit": "15",
            "lang": lang_param,
        }
        url = "https://photon.komoot.io/api/?" + urlencode(params)
        try:
            data = _fetch_json(url, headers=headers, timeout=20)
        except _GEOCODE_EXCEPTIONS:
            continue
        features = data.get("features") if isinstance(data, dict) else None
        if not features:
            continue
        for feature in features:
            if not isinstance(feature, dict):
                continue
            geometry = feature.get("geometry", {})
            coords = geometry.get("coordinates")
            if not (isinstance(coords, list) and len(coords) >= 2):
                continue
            props = feature.get("properties", {})
            if not isinstance(props, dict):
                props = {}
            score = 0.0
            house = props.get("housenumber")
            if house:
                normalized_house = _normalized_house(str(house))
                if normalized_house in house_tokens:
                    score += 5.0
                else:
                    for token in house_tokens:
                        if token and token in normalized_house:
                            score += 3.0
                            break
            street = (props.get("street") or "").lower()
            if street and street in address_lower:
                score += 1.0
            name = (props.get("name") or "").lower()
            if name and name in address_lower:
                score += 0.5
            city = (props.get("city") or "").lower()
            if city and city in address_lower:
                score += 0.25
            postcode = str(props.get("postcode") or "")
            if postcode and postcode in addr:
                score += 0.25
            osm_value = (props.get("osm_value") or "").lower()
            if osm_value in {"bridge", "street"}:
                score -= 1.0
            if score > best_score and score > 0:
                try:
                    best_coords = (float(coords[1]), float(coords[0]))
                except (TypeError, ValueError):
                    continue
                best_score = score
                if score >= 5.0:
                    return best_coords
    return best_coords


def geocode_to_coords(
    addr: str,
    *,
    prefer: str = "yandex",
    apikey: str | None = None,
    lang: str = "ru_RU",
) -> tuple[float, float] | None:
    cache = _load_cache()
    prefer_key = f"{prefer}:{addr}"
    cache_keys = [prefer_key, addr]
    for key in cache_keys:
        cached = cache.get(key)
        if isinstance(cached, list) and len(cached) == 2:
            return float(cached[0]), float(cached[1])
    prefer_normalized = (prefer or "").lower()
    lang_short = lang.split("_")[0] if lang else "en"
    email = os.environ.get("NOMINATIM_EMAIL")

    def _try(callable_obj):
        try:
            return callable_obj()
        except _GEOCODE_EXCEPTIONS:
            return None

    result: tuple[float, float] | None = None
    if prefer_normalized == "yandex":
        if apikey:
            result = _try(lambda: _yandex_geocode(addr, apikey, lang=lang))
        if result is None:
            result = _try(lambda: _nominatim_geocode(addr, lang=lang_short, email=email))
    elif prefer_normalized == "photon":
        result = _try(lambda: _photon_geocode(addr, lang=lang_short))
        if result is None and apikey:
            result = _try(lambda: _yandex_geocode(addr, apikey, lang=lang))
        if result is None:
            result = _try(lambda: _nominatim_geocode(addr, lang=lang_short, email=email))
    else:
        result = _try(lambda: _nominatim_geocode(addr, lang=lang_short, email=email))
        if result is None and apikey:
            result = _try(lambda: _yandex_geocode(addr, apikey, lang=lang))

    if result is None:
        result = _try(lambda: _photon_geocode(addr, lang=lang_short))

    if result is not None:
        lat_val = float(result[0])
        lon_val = float(result[1])
        for key in cache_keys:
            cache[key] = [lat_val, lon_val]
        _save_cache(cache)
    else:
        # Remove stale failure entries to allow future retries with new data
        modified = False
        for key in cache_keys:
            if key in cache and not isinstance(cache[key], list):
                cache.pop(key, None)
                modified = True
        if modified:
            _save_cache(cache)
    return result


def _parse_label_and_target(raw: str):
    # Supports two formats:
    # 1) "Address text"  -> label=raw, target=raw
    # 2) "Address text | lat,lon" -> label=left, target=right (if right looks like coords)
    if "|" in raw:
        left, right = raw.split("|", 1)
        left = left.strip()
        right = right.strip()
        if _is_coords(right):
            return left, right
        # if right isn't coords, fall back to full raw as address
    return raw.strip(), raw.strip()


def main(argv):
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Generate Yandex Maps deep links (public transport) for a list of addresses."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="addresses.txt",
        help="Path to input text file with one address per line (default: addresses.txt)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="links.csv",
        help="Output CSV file path (default: links.csv)",
    )
    parser.add_argument(
        "--domain",
        default="yandex.ru",
        help="Yandex domain to use (yandex.ru or yandex.com). Default: yandex.ru",
    )
    parser.add_argument(
        "--geocoder",
        choices=["yandex", "nominatim", "photon"],
        default="yandex",
        help="Preferred geocoder (default: yandex)",
    )
    parser.add_argument(
        "--apikey",
        default=DEFAULT_YANDEX_API_KEY,
        help="Yandex Geocoder API key (default: value from yandex_api_key.py or YANDEX_GEOCODER_API_KEY env var)",
    )
    parser.add_argument(
        "--prepend",
        default=os.environ.get("ADDRESS_PREPEND", ""),
        help="Prefix to prepend to address for geocoding context (e.g., 'Москва, ')",
    )
    parser.add_argument(
        "--format",
        choices=["csv", "pairs"],
        default="csv",
        help="Output format: csv (Address,Link) or pairs (Address/Link) per line",
    )

    args = parser.parse_args(argv)

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"Input file not found: {in_path}", file=sys.stderr)
        return 2

    encoding_used, lines = read_lines_with_fallback(in_path)
    # Filter out empty/comment lines
    addresses = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]

    rows = []
    for raw in addresses:
        label, target = _parse_label_and_target(raw)
        # Geocode non-coordinate targets
        if not _is_coords(target):
            query = (args.prepend + target) if args.prepend else target
            coords = geocode_to_coords(query, prefer=args.geocoder, apikey=(args.apikey or None))
            if coords:
                target = f"{coords[0]},{coords[1]}"
        link = build_yandex_link(target, args.domain)
        rows.append((label, link))

    out_path = Path(args.output)
    if args.format == "csv":
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Address", "YandexMapsLink"])
            writer.writerows(rows)
    else:
        with out_path.open("w", encoding="utf-8") as f:
            for a, l in rows:
                f.write(f"{a}/{l}\n\n")

    # Also echo a short summary to stdout
    print(f"Read {len(addresses)} addresses from {in_path} (encoding: {encoding_used}).")
    print(f"Wrote {len(rows)} rows to {out_path}.")
    if rows:
        preview = "\n".join([f"- {a} => {l}" for a, l in rows[:5]])
        print("Preview:\n" + preview)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
