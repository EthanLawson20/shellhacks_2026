import json
import os
from typing import Any, Optional
from urllib.request import Request, urlopen


def fetch_json(endpoint: str, base_url: Optional[str] = None, timeout: float = 10.0) -> Any:
    """Fetch and decode a JSON response from the Railway backend."""
    service_url = base_url or os.environ.get("RAILWAY_API_URL")
    if not service_url:
        raise ValueError("Set RAILWAY_API_URL or pass base_url.")

    if not service_url.startswith(("https://", "http://")):
        raise ValueError("The Railway backend URL must start with http:// or https://.")

    url = f"{service_url.rstrip('/')}/{endpoint.lstrip('/')}"
    request = Request(url, headers={"Accept": "application/json"})

    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_latest(timeout: float = 5.0) -> Any:
    """Fetch the latest ESP32 data using the configured Railway endpoint."""
    endpoint = os.environ.get("RAILWAY_DATA_ENDPOINT", "/api/data")
    return fetch_json(endpoint, timeout=timeout)