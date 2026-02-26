"""Mock data for NAIS workloads and deployments tests."""

MOCK_WORKLOADS_RAW = [
    {
        "__typename": "Application",
        "id": "app-1",
        "name": "my-app",
        "state": "NAIS_APPLICATION_STATE_RUNNING",
        "team": {"slug": "team-alpha"},
        "teamEnvironment": {
            "gcpProjectID": "my-gcp-project",
            "environment": {"name": "prod"},
        },
        "image": {"name": "ghcr.io/navikt/my-app", "tag": "abc123"},
        "ingresses": [{"host": "my-app.intern.nav.no"}],
    },
    {
        "__typename": "Job",
        "id": "job-1",
        "name": "my-job",
        "state": "NAIS_JOB_STATE_RUNNING",
        "team": {"slug": "team-alpha"},
        "teamEnvironment": {
            "gcpProjectID": "my-gcp-project",
            "environment": {"name": "prod"},
        },
        "image": {"name": "ghcr.io/navikt/my-job", "tag": "def456"},
    },
]

MOCK_DEPLOYMENTS_RAW = [
    {
        "id": "deploy-1",
        "createdAt": "2024-06-01T12:00:00Z",
        "teamSlug": "team-alpha",
        "environmentName": "prod",
        "repository": "navikt/my-app",
        "deployerUsername": "alice",
        "commitSha": "abc123def456",
        "triggerUrl": "https://github.com/navikt/my-app/actions/runs/123",
    },
    {
        "id": "deploy-2",
        "createdAt": "2024-06-02T10:00:00Z",
        "teamSlug": "team-alpha",
        "environmentName": "prod",
        "repository": None,
        "deployerUsername": None,
        "commitSha": None,
        "triggerUrl": None,
    },
]
