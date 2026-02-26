"""
Minimal GraphQL client for the NAIS API.

Handles authenticated POST requests and cursor-based pagination.
"""
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


class NaisGraphQLClient:
    def __init__(self, api_key: str, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a GraphQL query and return the parsed JSON response."""
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        response = self._session.post(self._base_url, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()

        if "errors" in result:
            raise RuntimeError(f"NAIS GraphQL errors: {result['errors']}")

        return result.get("data", {})

    def paginate(
        self,
        query: str,
        data_path: list[str],
        variables: dict[str, Any] | None = None,
        page_size: int = 100,
    ) -> list[Any]:
        """
        Collect all nodes from a paginated connection.

        :param query: GraphQL query string. Must include $cursor and $first variables,
                      and expose pageInfo { hasNextPage endCursor } at the connection root.
        :param data_path: List of keys to drill into the response data to reach the connection
                          object, e.g. ["teams"] or ["environment", "workloads"].
        :param variables: Additional query variables to send on every request.
        :param page_size: Number of items to request per page.
        """
        variables = dict(variables or {})
        variables["first"] = page_size
        variables.setdefault("cursor", None)

        nodes: list[Any] = []

        while True:
            data = self.query(query, variables)

            # Drill down to the connection object
            connection: Any = data
            for key in data_path:
                connection = connection[key]

            nodes.extend(connection.get("nodes", []))

            page_info = connection.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            variables["cursor"] = page_info["endCursor"]

        return nodes
