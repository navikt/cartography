from unittest.mock import MagicMock

import os

import cartography.intel.nais
import cartography.intel.nais.workloads
import tests.data.nais.workloads
from cartography.util import run_analysis_job
from tests.integration.util import check_nodes
from tests.integration.util import check_rels

NAIS_ANALYSIS_DIR = os.path.join(
    os.path.dirname(cartography.intel.nais.__file__),
    "..",
    "..",
    "data",
    "jobs",
    "analysis",
    "nais",
)

TEST_UPDATE_TAG = 123456789
TEST_TENANT_ID = "https://console.nav.cloud.nais.io/query"
COMMON_JOB_PARAMETERS = {
    "UPDATE_TAG": TEST_UPDATE_TAG,
    "TENANT_ID": TEST_TENANT_ID,
    "NAIS_TENANT_ID": TEST_TENANT_ID,
}


def _seed_github_users(neo4j_session) -> None:
    """Seed minimal GitHubUser nodes for deployer MatchLink tests."""
    neo4j_session.run(
        """
        MERGE (u:GitHubUser {id: 'https://github.com/alice'})
        SET u.username = 'alice', u.lastupdated = $update_tag
        MERGE (u2:GitHubUser {id: 'https://github.com/bob'})
        SET u2.username = 'bob', u2.lastupdated = $update_tag
        MERGE (u3:GitHubUser {id: 'https://github.com/carol'})
        SET u3.username = 'carol', u3.lastupdated = $update_tag
        """,
        update_tag=TEST_UPDATE_TAG,
    )


def test_transform_workloads():
    # Act
    apps, deployments = cartography.intel.nais.workloads.transform_workloads(
        tests.data.nais.workloads.MOCK_WORKLOADS_RAW
    )

    # Assert — apps
    assert len(apps) == 3

    app = next(a for a in apps if a["name"] == "my-app")
    assert app["workload_type"] == "Application"
    assert app["team_slug"] == "team-alpha"
    assert app["environment"] == "prod"
    assert app["image_name"] == "ghcr.io/navikt/my-app"
    assert app["image_tag"] == "abc123"
    assert app["ingresses"] == ["https://my-app.intern.nav.no"]
    # Has one RUNNING instance — Kubernetes confirms it is live.
    assert app["has_running_instance"] is True

    stopped_app = next(a for a in apps if a["name"] == "my-stopped-app")
    assert stopped_app["workload_type"] == "Application"
    # No running instances — should not receive ACTIVE_DEPLOYMENT.
    assert stopped_app["has_running_instance"] is False

    job = next(a for a in apps if a["name"] == "my-job")
    assert job["workload_type"] == "Job"
    assert job["ingresses"] == []
    # Jobs are always considered active — they run on a schedule.
    assert job["has_running_instance"] is True

    # Assert — deployments
    # 4 total: deploy-1 and deploy-old for app-1, deploy-3 for app-2, deploy-2 for job-1
    assert len(deployments) == 4

    d1 = next(d for d in deployments if d["id"] == "deploy-1")
    assert d1["app_id"] == "app-1"
    assert d1["latest_status"] == "SUCCESS"
    assert d1["is_active"] is True
    assert d1["repository_url"] == "https://github.com/navikt/my-app"

    d_old = next(d for d in deployments if d["id"] == "deploy-old")
    assert d_old["app_id"] == "app-1"
    assert d_old["latest_status"] == "FAILURE"
    assert d_old["is_active"] is False

    d3 = next(d for d in deployments if d["id"] == "deploy-3")
    assert d3["app_id"] == "app-2"
    assert d3["latest_status"] == "SUCCESS"
    # is_active is NAIS heuristic metadata — still set correctly for stopped app.
    assert d3["is_active"] is True

    d2 = next(d for d in deployments if d["id"] == "deploy-2")
    assert d2["app_id"] == "job-1"
    assert d2["latest_status"] is None
    assert d2["is_active"] is False
    assert d2["repository"] is None
    assert d2["repository_url"] is None


def test_load_nais_workloads(neo4j_session):
    """NaisApp and NaisDeployment nodes are loaded with correct properties."""
    # Arrange
    client = MagicMock()

    # Act
    cartography.intel.nais.workloads.sync(
        neo4j_session,
        client,
        TEST_TENANT_ID,
        TEST_UPDATE_TAG,
        COMMON_JOB_PARAMETERS,
        _workloads_raw=tests.data.nais.workloads.MOCK_WORKLOADS_RAW,
    )

    # Assert — apps exist
    expected_apps = {
        ("app-1", "my-app"),
        ("app-2", "my-stopped-app"),
        ("job-1", "my-job"),
    }
    assert check_nodes(neo4j_session, "NaisApp", ["id", "name"]) == expected_apps

    # Assert — has_running_instance set correctly on NaisApp nodes
    running = {
        row["a.id"]
        for row in neo4j_session.run(
            "MATCH (a:NaisApp) WHERE a.has_running_instance = true RETURN a.id"
        )
    }
    assert running == {"app-1", "job-1"}
    stopped = {
        row["a.id"]
        for row in neo4j_session.run(
            "MATCH (a:NaisApp) WHERE a.has_running_instance = false RETURN a.id"
        )
    }
    assert stopped == {"app-2"}

    # Assert — all deployments exist
    expected_deployment_ids = {"deploy-1", "deploy-old", "deploy-2", "deploy-3"}
    actual_ids = {
        row["d.id"] for row in neo4j_session.run("MATCH (d:NaisDeployment) RETURN d.id")
    }
    assert actual_ids == expected_deployment_ids

    # Assert — is_active flag still set as read-only NAIS heuristic metadata
    active_ids = {
        row["d.id"]
        for row in neo4j_session.run(
            "MATCH (d:NaisDeployment) WHERE d.is_active = true RETURN d.id"
        )
    }
    assert active_ids == {"deploy-1", "deploy-3"}

    # Assert — NaisApp-[:HAS_DEPLOYMENT]->NaisDeployment relationships exist
    assert check_rels(
        neo4j_session,
        "NaisApp",
        "id",
        "NaisDeployment",
        "id",
        "HAS_DEPLOYMENT",
        rel_direction_right=True,
    ) == {
        ("app-1", "deploy-1"),
        ("app-1", "deploy-old"),
        ("app-2", "deploy-3"),
        ("job-1", "deploy-2"),
    }


def test_load_deployer_links(neo4j_session):
    """GitHubUser-[:TRIGGERED_BY]->NaisDeployment edges are created for known deployers."""
    # Arrange
    _seed_github_users(neo4j_session)
    client = MagicMock()

    # Act
    cartography.intel.nais.workloads.sync(
        neo4j_session,
        client,
        TEST_TENANT_ID,
        TEST_UPDATE_TAG,
        COMMON_JOB_PARAMETERS,
        _workloads_raw=tests.data.nais.workloads.MOCK_WORKLOADS_RAW,
    )

    # Assert — known deployers are linked
    assert check_rels(
        neo4j_session,
        "GitHubUser",
        "username",
        "NaisDeployment",
        "id",
        "TRIGGERED_BY",
        rel_direction_right=True,
    ) == {
        ("alice", "deploy-1"),
        ("bob", "deploy-old"),
        ("carol", "deploy-3"),
    }


def test_deployer_link_skipped_when_no_github_user(neo4j_session):
    """TRIGGERED_BY edge is silently skipped when GitHubUser does not exist."""
    # Arrange — ensure no GitHubUser nodes exist
    neo4j_session.run("MATCH (u:GitHubUser) DETACH DELETE u")
    client = MagicMock()

    # Act
    cartography.intel.nais.workloads.sync(
        neo4j_session,
        client,
        TEST_TENANT_ID,
        TEST_UPDATE_TAG,
        COMMON_JOB_PARAMETERS,
        _workloads_raw=tests.data.nais.workloads.MOCK_WORKLOADS_RAW,
    )

    # Assert — no TRIGGERED_BY edges created (GitHubUser nodes don't exist)
    result = neo4j_session.run(
        "MATCH ()-[r:TRIGGERED_BY]->() RETURN count(r) AS cnt"
    ).single()
    assert result["cnt"] == 0


def test_deployer_link_cleanup(neo4j_session):
    """Stale TRIGGERED_BY edges are removed on the next sync with a new update tag."""
    # Arrange
    _seed_github_users(neo4j_session)
    client = MagicMock()

    # Act — first sync
    cartography.intel.nais.workloads.sync(
        neo4j_session,
        client,
        TEST_TENANT_ID,
        TEST_UPDATE_TAG,
        COMMON_JOB_PARAMETERS,
        _workloads_raw=tests.data.nais.workloads.MOCK_WORKLOADS_RAW,
    )

    # Assert — edges exist after first sync
    result = neo4j_session.run(
        "MATCH ()-[r:TRIGGERED_BY]->() RETURN count(r) AS cnt"
    ).single()
    assert result["cnt"] == 3

    # Act — second sync with new update tag (simulates deployments no longer returned)
    new_tag = TEST_UPDATE_TAG + 1
    new_params = {**COMMON_JOB_PARAMETERS, "UPDATE_TAG": new_tag}
    cartography.intel.nais.workloads.sync(
        neo4j_session,
        client,
        TEST_TENANT_ID,
        new_tag,
        new_params,
        _workloads_raw=[],  # empty — all deployments are stale
    )

    # Assert — stale edges removed
    result = neo4j_session.run(
        "MATCH ()-[r:TRIGGERED_BY]->() RETURN count(r) AS cnt"
    ).single()
    assert result["cnt"] == 0


def test_nais_gar_link_no_gar_nodes(neo4j_session):
    """nais_gar_link analysis job is a no-op when GCPArtifactRegistryRepositoryImage nodes are absent."""
    # Arrange — load apps so NaisApp nodes exist, but no GAR nodes
    client = MagicMock()
    cartography.intel.nais.workloads.sync(
        neo4j_session,
        client,
        TEST_TENANT_ID,
        TEST_UPDATE_TAG,
        COMMON_JOB_PARAMETERS,
        _workloads_raw=tests.data.nais.workloads.MOCK_WORKLOADS_RAW,
    )
    gar_link_job = os.path.join(NAIS_ANALYSIS_DIR, "nais_gar_link.json")

    # Act — run the analysis job directly; should not raise
    run_analysis_job(gar_link_job, neo4j_session, COMMON_JOB_PARAMETERS)

    # Assert — no RUNS_GAR_IMAGE edges created (no GAR nodes in graph)
    result = neo4j_session.run(
        "MATCH ()-[r:RUNS_GAR_IMAGE]->() RETURN count(r) AS cnt"
    ).single()
    assert result["cnt"] == 0


def test_active_deployment_analysis_job(neo4j_session):
    """ACTIVE_DEPLOYMENT edge is created only for apps with has_running_instance=true,
    and always points to the single most recent deployment for that app."""
    # Arrange
    client = MagicMock()
    cartography.intel.nais.workloads.sync(
        neo4j_session,
        client,
        TEST_TENANT_ID,
        TEST_UPDATE_TAG,
        COMMON_JOB_PARAMETERS,
        _workloads_raw=tests.data.nais.workloads.MOCK_WORKLOADS_RAW,
    )
    active_deployment_job = os.path.join(NAIS_ANALYSIS_DIR, "nais_active_deployment.json")

    # Act
    run_analysis_job(active_deployment_job, neo4j_session, COMMON_JOB_PARAMETERS)

    # Assert — ACTIVE_DEPLOYMENT edges exist for running app and job, not for stopped app
    active_edges = check_rels(
        neo4j_session,
        "NaisApp",
        "id",
        "NaisDeployment",
        "id",
        "ACTIVE_DEPLOYMENT",
        rel_direction_right=True,
    )
    # my-app (has_running_instance=True) → most recent deployment is deploy-1
    assert ("app-1", "deploy-1") in active_edges
    # my-job (has_running_instance=True, Job) → most recent deployment is deploy-2
    assert ("job-1", "deploy-2") in active_edges
    # my-stopped-app (has_running_instance=False) → no ACTIVE_DEPLOYMENT edge
    assert not any(app_id == "app-2" for app_id, _ in active_edges)
    # Exactly one edge per active workload — no fan-out
    assert len(active_edges) == 2


def test_active_deployment_picks_most_recent(neo4j_session):
    """ACTIVE_DEPLOYMENT always points to the most recent deployment, not is_active."""
    # Arrange — reset graph so nodes from other tests don't bleed in.
    # App has two deployments: most recent is FAILURE (is_active=False),
    # older one is SUCCESS (is_active=True). The most recent must win.
    neo4j_session.run("MATCH (n) DETACH DELETE n")
    raw = [
        {
            "__typename": "Application",
            "id": "app-order",
            "name": "order-test-app",
            "appState": "NAIS_APPLICATION_STATE_RUNNING",
            "team": {"slug": "team-beta"},
            "teamEnvironment": {
                "gcpProjectID": "proj",
                "environment": {"name": "dev"},
            },
            "image": {"name": "ghcr.io/navikt/order-test", "tag": "latest"},
            "ingresses": [],
            "instances": {"nodes": [{"status": {"state": "RUNNING"}}]},
            "deployments": {
                "nodes": [
                    {
                        # Most recent — FAILURE
                        "id": "deploy-new",
                        "createdAt": "2024-07-01T10:00:00Z",
                        "teamSlug": "team-beta",
                        "environmentName": "dev",
                        "repository": "navikt/order-test",
                        "deployerUsername": None,
                        "commitSha": "newsha",
                        "triggerUrl": None,
                        "statuses": {"nodes": [{"state": "FAILURE"}]},
                    },
                    {
                        # Older — SUCCESS (is_active=True by NAIS heuristic)
                        "id": "deploy-prev",
                        "createdAt": "2024-06-30T10:00:00Z",
                        "teamSlug": "team-beta",
                        "environmentName": "dev",
                        "repository": "navikt/order-test",
                        "deployerUsername": None,
                        "commitSha": "prevsha",
                        "triggerUrl": None,
                        "statuses": {"nodes": [{"state": "SUCCESS"}]},
                    },
                ]
            },
        }
    ]
    client = MagicMock()
    cartography.intel.nais.workloads.sync(
        neo4j_session,
        client,
        TEST_TENANT_ID,
        TEST_UPDATE_TAG,
        COMMON_JOB_PARAMETERS,
        _workloads_raw=raw,
    )
    active_deployment_job = os.path.join(NAIS_ANALYSIS_DIR, "nais_active_deployment.json")

    # Act
    run_analysis_job(active_deployment_job, neo4j_session, COMMON_JOB_PARAMETERS)

    # Assert — most recent deployment wins regardless of is_active / latest_status
    active_edges = check_rels(
        neo4j_session,
        "NaisApp",
        "id",
        "NaisDeployment",
        "id",
        "ACTIVE_DEPLOYMENT",
        rel_direction_right=True,
    )
    assert active_edges == {("app-order", "deploy-new")}


def test_active_deployment_cleanup(neo4j_session):
    """Stale ACTIVE_DEPLOYMENT edges are removed when the app no longer has running instances."""
    # Arrange — reset graph, then first sync with app running
    neo4j_session.run("MATCH (n) DETACH DELETE n")
    client = MagicMock()
    cartography.intel.nais.workloads.sync(
        neo4j_session,
        client,
        TEST_TENANT_ID,
        TEST_UPDATE_TAG,
        COMMON_JOB_PARAMETERS,
        _workloads_raw=tests.data.nais.workloads.MOCK_WORKLOADS_RAW,
    )
    active_deployment_job = os.path.join(NAIS_ANALYSIS_DIR, "nais_active_deployment.json")
    run_analysis_job(active_deployment_job, neo4j_session, COMMON_JOB_PARAMETERS)

    # Assert — edges exist after first sync
    result = neo4j_session.run(
        "MATCH ()-[r:ACTIVE_DEPLOYMENT]->() RETURN count(r) AS cnt"
    ).single()
    assert result["cnt"] == 2

    # Arrange — second sync: app-1 now has no running instances
    new_tag = TEST_UPDATE_TAG + 1
    new_params = {**COMMON_JOB_PARAMETERS, "UPDATE_TAG": new_tag}
    stopped_raw = [
        {
            **tests.data.nais.workloads.MOCK_WORKLOADS_RAW[0],
            "instances": {"nodes": []},  # no longer running
        },
        tests.data.nais.workloads.MOCK_WORKLOADS_RAW[1],  # my-stopped-app unchanged
        tests.data.nais.workloads.MOCK_WORKLOADS_RAW[2],  # my-job unchanged
    ]

    # Act — second sync
    cartography.intel.nais.workloads.sync(
        neo4j_session,
        client,
        TEST_TENANT_ID,
        new_tag,
        new_params,
        _workloads_raw=stopped_raw,
    )
    run_analysis_job(active_deployment_job, neo4j_session, new_params)

    # Assert — only the job edge remains; app-1 edge is gone
    active_edges = check_rels(
        neo4j_session,
        "NaisApp",
        "id",
        "NaisDeployment",
        "id",
        "ACTIVE_DEPLOYMENT",
        rel_direction_right=True,
    )
    assert active_edges == {("job-1", "deploy-2")}
