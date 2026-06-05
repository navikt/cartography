from unittest.mock import MagicMock

import cartography.intel.nais.workloads
import tests.data.nais.workloads
from tests.integration.util import check_nodes
from tests.integration.util import check_rels

TEST_UPDATE_TAG = 123456789
TEST_TENANT_ID = "https://console.nav.cloud.nais.io/query"
COMMON_JOB_PARAMETERS = {
    "UPDATE_TAG": TEST_UPDATE_TAG,
    "TENANT_ID": TEST_TENANT_ID,
    "NAIS_TENANT_ID": TEST_TENANT_ID,
}


def test_transform_workloads():
    # Act
    apps, deployments = cartography.intel.nais.workloads.transform_workloads(
        tests.data.nais.workloads.MOCK_WORKLOADS_RAW
    )

    # Assert — apps
    assert len(apps) == 2

    app = next(a for a in apps if a["name"] == "my-app")
    assert app["workload_type"] == "Application"
    assert app["team_slug"] == "team-alpha"
    assert app["environment"] == "prod"
    assert app["image_name"] == "ghcr.io/navikt/my-app"
    assert app["image_tag"] == "abc123"
    assert app["ingresses"] == ["https://my-app.intern.nav.no"]

    job = next(a for a in apps if a["name"] == "my-job")
    assert job["workload_type"] == "Job"
    assert job["ingresses"] == []

    # Assert — deployments
    # 3 total: deploy-1 and deploy-old for app-1, deploy-2 for job-1
    assert len(deployments) == 3

    d1 = next(d for d in deployments if d["id"] == "deploy-1")
    assert d1["app_id"] == "app-1"
    assert d1["latest_status"] == "SUCCESS"
    assert d1["is_active"] is True
    assert d1["repository_url"] == "https://github.com/navikt/my-app"

    d_old = next(d for d in deployments if d["id"] == "deploy-old")
    assert d_old["app_id"] == "app-1"
    assert d_old["latest_status"] == "FAILURE"
    assert d_old["is_active"] is False

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
    expected_apps = {("app-1", "my-app"), ("job-1", "my-job")}
    assert check_nodes(neo4j_session, "NaisApp", ["id", "name"]) == expected_apps

    # Assert — all deployments exist
    expected_deployment_ids = {"deploy-1", "deploy-old", "deploy-2"}
    actual_ids = {
        row["d.id"] for row in neo4j_session.run("MATCH (d:NaisDeployment) RETURN d.id")
    }
    assert actual_ids == expected_deployment_ids

    # Assert — is_active flag set correctly
    active_ids = {
        row["d.id"]
        for row in neo4j_session.run(
            "MATCH (d:NaisDeployment) WHERE d.is_active = true RETURN d.id"
        )
    }
    assert active_ids == {"deploy-1"}

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
        ("job-1", "deploy-2"),
    }
