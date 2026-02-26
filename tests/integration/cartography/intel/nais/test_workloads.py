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
    apps = cartography.intel.nais.workloads.transform_workloads(
        tests.data.nais.workloads.MOCK_WORKLOADS_RAW
    )
    assert len(apps) == 2

    app = next(a for a in apps if a["name"] == "my-app")
    assert app["workload_type"] == "Application"
    assert app["team_slug"] == "team-alpha"
    assert app["environment"] == "prod"
    assert app["image_name"] == "ghcr.io/navikt/my-app"
    assert app["image_tag"] == "abc123"
    assert app["ingresses"] == ["my-app.intern.nav.no"]

    job = next(a for a in apps if a["name"] == "my-job")
    assert job["workload_type"] == "Job"
    assert job["ingresses"] == []


def test_transform_deployments():
    deployments = cartography.intel.nais.workloads.transform_deployments(
        tests.data.nais.workloads.MOCK_DEPLOYMENTS_RAW
    )
    assert len(deployments) == 2

    d = next(dep for dep in deployments if dep["id"] == "deploy-1")
    assert d["repository"] == "navikt/my-app"
    assert d["commit_sha"] == "abc123def456"


def test_load_nais_workloads(neo4j_session):
    """NaisApp and NaisDeployment nodes are loaded."""
    client = MagicMock()

    cartography.intel.nais.workloads.sync(
        neo4j_session,
        client,
        TEST_TENANT_ID,
        TEST_UPDATE_TAG,
        COMMON_JOB_PARAMETERS,
        _workloads_raw=tests.data.nais.workloads.MOCK_WORKLOADS_RAW,
        _deployments_raw=tests.data.nais.workloads.MOCK_DEPLOYMENTS_RAW,
    )

    # Apps exist
    expected_apps = {("app-1", "my-app"), ("job-1", "my-job")}
    assert check_nodes(neo4j_session, "NaisApp", ["id", "name"]) == expected_apps

    # Deployments exist
    expected_deployments = {("deploy-1", "navikt/my-app"), ("deploy-2", None)}
    assert (
        check_nodes(neo4j_session, "NaisDeployment", ["id", "repository"])
        == expected_deployments
    )
