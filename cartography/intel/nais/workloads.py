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
query GetWorkloads($env: String!, $first: Int!, $cursor: Cursor, $deploymentLimit: Int!) {
  environment(name: $env) {
    workloads(first: $first, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        ... on Application {
          __typename
          id
          name
          appState: state
          team { slug }
          teamEnvironment {
            gcpProjectID
            environment { name }
          }
          image { name tag }
          ingresses { url }
          deployments(first: $deploymentLimit) {
            nodes {
              id
              createdAt
              teamSlug
              environmentName
              repository
              deployerUsername
              commitSha
              triggerUrl
              statuses(first: 1) {
                nodes { state }
              }
            }
          }
        }
        ... on Job {
          __typename
          id
          name
          jobState: state
          team { slug }
          teamEnvironment {
            gcpProjectID
            environment { name }
          }
          image { name tag }
          deployments(first: $deploymentLimit) {
            nodes {
              id
              createdAt
              teamSlug
              environmentName
              repository
              deployerUsername
              commitSha
              triggerUrl
              statuses(first: 1) {
                nodes { state }
              }
            }
          }
        }
      }
    }
  }
}
"""


def get_environments(client: NaisGraphQLClient) -> list[str]:
    data = client.query(ENVIRONMENTS_QUERY)
    return [e["name"] for e in (data.get("environments") or {}).get("nodes") or []]


def get_workloads(
    client: NaisGraphQLClient,
    deployment_limit: int = 10,
) -> list[dict[str, Any]]:
    environments = get_environments(client)
    logger.info(
        "NAIS workloads: fetching workloads for %d environments", len(environments)
    )
    workloads = []
    for idx, env in enumerate(environments, start=1):
        results = client.paginate(
            WORKLOADS_QUERY,
            ["environment", "workloads"],
            variables={"env": env, "deploymentLimit": deployment_limit},
        )
        workloads.extend(results)
        logger.info(
            "NAIS workloads: environment %d/%d '%s' — %d workloads (total so far: %d)",
            idx,
            len(environments),
            env,
            len(results),
            len(workloads),
        )
    return workloads


def transform_workloads(
    raw: list[dict[str, Any]],
) -> tuple[list[dict], list[dict]]:
    """Return (apps, deployments) extracted from raw workload nodes.

    Deployments are fetched inline per workload (most-recent-first).
    The first deployment per workload whose latest status is SUCCESS is
    flagged is_active=True; all others are False.
    """
    apps = []
    all_deployments: list[dict] = []

    for w in raw:
        team = w.get("team") or {}
        team_env = w.get("teamEnvironment") or {}
        env = team_env.get("environment") or {}
        image = w.get("image") or {}
        ingress_urls = [i["url"] for i in (w.get("ingresses") or []) if i.get("url")]

        app_id = w["id"]
        apps.append(
            {
                "id": app_id,
                "name": w.get("name"),
                "workload_type": w.get("__typename"),
                "team_slug": team.get("slug"),
                "environment": env.get("name"),
                "gcp_project_id": team_env.get("gcpProjectID"),
                "image_name": image.get("name"),
                "image_tag": image.get("tag"),
                "state": w.get("appState") or w.get("jobState"),
                "ingresses": ingress_urls,
            }
        )

        raw_deps = (w.get("deployments") or {}).get("nodes") or []
        active_found = False
        for d in raw_deps:
            statuses = (d.get("statuses") or {}).get("nodes") or []
            latest_status = statuses[0]["state"] if statuses else None

            is_active = False
            if not active_found and latest_status == "SUCCESS":
                is_active = True
                active_found = True

            repo = d.get("repository")
            # Fall back to parent workload team slug if not on the deployment node
            team_slug = d.get("teamSlug") or team.get("slug")
            all_deployments.append(
                {
                    "id": d["id"],
                    "created_at": d.get("createdAt"),
                    "team_slug": team_slug,
                    "environment_name": d.get("environmentName"),
                    "repository": repo,
                    "repository_url": f"https://github.com/{repo}" if repo else None,
                    "deployer_username": d.get("deployerUsername"),
                    "commit_sha": d.get("commitSha"),
                    "trigger_url": d.get("triggerUrl"),
                    "latest_status": latest_status,
                    "is_active": is_active,
                    "app_id": app_id,
                }
            )

    return apps, all_deployments


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
    GraphJob.from_node_schema(NaisDeploymentSchema(), common_job_parameters).run(
        neo4j_session
    )


@timeit
def sync(
    neo4j_session: neo4j.Session,
    client: NaisGraphQLClient,
    tenant_id: str,
    update_tag: int,
    common_job_parameters: dict[str, Any],
    deployment_limit: int = 10,
    _workloads_raw: list[dict[str, Any]] | None = None,
) -> None:
    logger.info("Syncing NAIS workloads")
    raw_workloads = (
        _workloads_raw
        if _workloads_raw is not None
        else get_workloads(client, deployment_limit)
    )
    apps, deployments = transform_workloads(raw_workloads)
    logger.info(
        "NAIS workloads: %d workloads, %d deployments to load",
        len(apps),
        len(deployments),
    )
    load_apps(neo4j_session, apps, tenant_id, update_tag)
    load_deployments(neo4j_session, deployments, tenant_id, update_tag)
    cleanup(neo4j_session, common_job_parameters)
    logger.info("NAIS workloads sync complete")
