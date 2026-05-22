import httpx

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Approximate geographic centres of Pakistan provinces / territories
_PROVINCE_COORDS: dict[str, tuple[float, float]] = {
    "punjab":           (31.1704, 72.7097),
    "sindh":            (25.8943, 68.5247),
    "kpk":              (34.9526, 72.3311),
    "balochistan":      (28.4907, 65.0958),
    "islamabad":        (33.7294, 73.0931),
    "federal":          (33.7294, 73.0931),
    "gilgit_baltistan": (35.8026, 74.9830),
    "azad_kashmir":     (34.0479, 73.9713),
}


async def geocode_address(address: str) -> tuple[float, float] | None:
    """Return (lat, lng) for a free-text address via Nominatim, or None on failure."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                _NOMINATIM_URL,
                params={"q": address, "format": "json", "limit": 1, "countrycodes": "pk"},
                headers={"User-Agent": "AttorneyAI/1.0 (muhammadusamahoyrr@gmail.com)"},
            )
            hits = resp.json()
            if hits:
                return float(hits[0]["lat"]), float(hits[0]["lon"])
    except Exception:
        pass
    return None


def province_coords(province: str | None) -> tuple[float, float] | None:
    """Return approximate centre coordinates for a Pakistan province slug."""
    if not province:
        return None
    key = province.lower().replace(" ", "_").replace("-", "_")
    return _PROVINCE_COORDS.get(key)
