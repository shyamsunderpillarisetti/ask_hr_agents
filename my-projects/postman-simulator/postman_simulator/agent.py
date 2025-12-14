from typing import Any, Dict, Optional


class PostmanSimulator:
    """Simple simulator that echoes a request and returns a fake response."""

    def send_request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        body: Any = None,
    ) -> Dict[str, Any]:
        headers = headers or {}
        return {
            "method": method,
            "url": url,
            "headers": headers,
            "body": body,
            "status": 200,
            "response": {"echo": {"method": method, "url": url, "body": body}},
        }
