"""
Minimal GraphQL client for the NAIS API.

Handles authenticated POST requests and cursor-based pagination.
"""

import logging
from typing import Any

import backoff
import requests

from cartography.util import backoff_handler

logger = logging.getLogger(__name__)

_MAX_TRIES = 4  # 1 initial + 3 retries (~1s, ~2s, ~4s backoff)


class NaisGraphQLClient:
    def __init__(self, token: str, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )

    def query(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Execute a GraphQL query and return the parsed JSON response.

        GraphQL errors in the response are logged as warnings and an empty dict
        is returned so the caller can continue rather than aborting the sync.
        HTTP errors are raised and will be retried by paginate().
        """
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        response = self._session.post(self._base_url, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()

        if "errors" in result:
            logger.warning(
                "NAIS GraphQL returned errors; continuing sync. errors=%s",
                result["errors"],
            )
            return {}

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

        Each page request is retried with exponential backoff on HTTP errors.

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
        page = 0

        @backoff.on_exception(
            backoff.expo,
            requests.exceptions.RequestException,
            max_tries=_MAX_TRIES,
            on_backoff=backoff_handler,
        )
        def _fetch_page() -> dict[str, Any]:
            return self.query(query, variables)

        while True:
            page += 1
            data = _fetch_page()

            if not data:
                # query() returned {} due to GraphQL errors — log and stop pagination
                logger.warning(
                    "NAIS paginate: empty response on page %d for path %s; stopping pagination.",
                    page,
                    data_path,
                )
                break

            # Drill down to the connection object
            connection: Any = data
            for key in data_path:
                connection = connection.get(key) or {}

            batch = connection.get("nodes", [])
            nodes.extend(batch)
            logger.debug(
                "NAIS paginate: path=%s page=%d fetched=%d total=%d",
                data_path,
                page,
                len(batch),
                len(nodes),
            )

            page_info = connection.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            variables["cursor"] = page_info["endCursor"]

        return nodes
