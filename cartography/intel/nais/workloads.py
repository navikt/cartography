import logging
from typing import Any

import neo4j

from cartography.client.core.tx import load
from cartography.graph.job import GraphJob
from cartography.intel.nais.client import NaisGraphQLClient
from cartography.models.nais.workload import NaisAppSchema
from cartography.models.nais.workload import NaisDeploymentSchema
from cartography.util import timeit

logger = logging.getLogger(__name__)

ENVIRONMENTS_QUERY = """
query GetEnvironments {
  environments {
    nodes { name }
  }
}
"""

WORKLOADS_QUERY = """
query GetWorkloads($env: String!, $first: Int!, $cursor: Cursor) {
  environment(name: $env) {
    workloads(first: $first, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        ... on Application {
          __typename
          id
          name
          state
          team { slug }
          teamEnvironment {
            gcpProjectID
            environment { name }
          }
          image { name tag }
          ingresses { host }
        }
        ... on Job {
          __typename
          id
          name
          state
          team { slug }
          teamEnvironment {
            gcpProjectID
            environment { name }
          }
          image { name tag }
        }
      }
    }
  }
}
"""

DEPLOYMENTS_QUERY = """
query GetDeployments($first: Int!, $cursor: Cursor) {
  deployments(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      createdAt
      teamSlug
      environmentName
      repository
      deployerUsername
      commitSha
      triggerUrl
    }
  }
}
"""


def get_environments(client: NaisGraphQLClient) -> list[str]:
    data = client.query(ENVIRONMENTS_QUERY)
    return [e["name"] for e in (data.get("environments") or {}).get("nodes") or []]


def get_workloads(client: NaisGraphQLClient) -> list[dict[str, Any]]:
    environments = get_environments(client)
    workloads = []
    for env in environments:
        logger.debug("Fetching NAIS workloads for environment %s", env)
        results = client.paginate(
            WORKLOADS_QUERY,
            ["environment", "workloads"],
            variables={"env": env},
        )
        workloads.extend(results)
    return workloads


def get_deployments(client: NaisGraphQLClient) -> list[dict[str, Any]]:
    return client.paginate(DEPLOYMENTS_QUERY, ["deployments"])


def transform_workloads(raw: list[dict[str, Any]]) -> list[dict]:
    apps = []
    for w in raw:
        team = w.get("team") or {}
        team_env = w.get("teamEnvironment") or {}
        env = team_env.get("environment") or {}
        image = w.get("image") or {}
        ingress_hosts = [i["host"] for i in (w.get("ingresses") or []) if i.get("host")]

        apps.append(
            {
                "id": w["id"],
                "name": w.get("name"),
                "workload_type": w.get("__typename"),
                "team_slug": team.get("slug"),
                "environment": env.get("name"),
                "gcp_project_id": team_env.get("gcpProjectID"),
                "image_name": image.get("name"),
                "image_tag": image.get("tag"),
                "state": w.get("state"),
                "ingresses": ingress_hosts,
            }
        )
    return apps


def transform_deployments(raw: list[dict[str, Any]]) -> list[dict]:
    return [
        {
            "id": d["id"],
            "created_at": d.get("createdAt"),
            "team_slug": d.get("teamSlug"),
            "environment_name": d.get("environmentName"),
            "repository": d.get("repository"),
            "deployer_username": d.get("deployerUsername"),
            "commit_sha": d.get("commitSha"),
            "trigger_url": d.get("triggerUrl"),
        }
        for d in raw
    ]


@timeit
def load_apps(
    neo4j_session: neo4j.Session,
    apps: list[dict],
    tenant_id: str,
    update_tag: int,
) -> None:
    load(
        neo4j_session,
        NaisAppSchema(),
        apps,
        lastupdated=update_tag,
        NAIS_TENANT_ID=tenant_id,
    )


@timeit
def load_deployments(
    neo4j_session: neo4j.Session,
    deployments: list[dict],
    tenant_id: str,
    update_tag: int,
) -> None:
    load(
        neo4j_session,
        NaisDeploymentSchema(),
        deployments,
        lastupdated=update_tag,
        NAIS_TENANT_ID=tenant_id,
    )


@timeit
def cleanup(
    neo4j_session: neo4j.Session,
    common_job_parameters: dict[str, Any],
) -> None:
    GraphJob.from_node_schema(NaisAppSchema(), common_job_parameters).run(neo4j_session)
    GraphJob.from_node_schema(NaisDeploymentSchema(), common_job_parameters).run(neo4j_session)


@timeit
def sync(
    neo4j_session: neo4j.Session,
    client: NaisGraphQLClient,
    tenant_id: str,
    update_tag: int,
    common_job_parameters: dict[str, Any],
    _workloads_raw: list[dict[str, Any]] | None = None,
    _deployments_raw: list[dict[str, Any]] | None = None,
) -> None:
    logger.info("Syncing NAIS workloads")
    raw_workloads = _workloads_raw if _workloads_raw is not None else get_workloads(client)
    apps = transform_workloads(raw_workloads)
    load_apps(neo4j_session, apps, tenant_id, update_tag)

    logger.info("Syncing NAIS deployments")
    raw_deployments = _deployments_raw if _deployments_raw is not None else get_deployments(client)
    deployments = transform_deployments(raw_deployments)
    load_deployments(neo4j_session, deployments, tenant_id, update_tag)

    cleanup(neo4j_session, common_job_parameters)
