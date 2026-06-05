"""Mock data for NAIS workloads and deployments tests."""

MOCK_WORKLOADS_RAW = [
    {
        "__typename": "Application",
        "id": "app-1",
        "name": "my-app",
        "appState": "NAIS_APPLICATION_STATE_RUNNING",
        "team": {"slug": "team-alpha"},
        "teamEnvironment": {
            "gcpProjectID": "my-gcp-project",
            "environment": {"name": "prod"},
        },
        "image": {"name": "ghcr.io/navikt/my-app", "tag": "abc123"},
        "ingresses": [{"url": "https://my-app.intern.nav.no"}],
        "deployments": {
            "nodes": [
                {
                    # Most recent — SUCCESS → is_active=True
                    "id": "deploy-1",
                    "createdAt": "2024-06-01T12:00:00Z",
                    "teamSlug": "team-alpha",
                    "environmentName": "prod",
                    "repository": "navikt/my-app",
                    "deployerUsername": "alice",
                    "commitSha": "abc123def456",
                    "triggerUrl": "https://github.com/navikt/my-app/actions/runs/123",
                    "statuses": {"nodes": [{"state": "SUCCESS"}]},
                },
                {
                    # Older deploy — FAILURE → is_active=False
                    "id": "deploy-old",
                    "createdAt": "2024-05-30T12:00:00Z",
                    "teamSlug": "team-alpha",
                    "environmentName": "prod",
                    "repository": "navikt/my-app",
                    "deployerUsername": "bob",
                    "commitSha": "oldhash123",
                    "triggerUrl": None,
                    "statuses": {"nodes": [{"state": "FAILURE"}]},
                },
            ]
        },
    },
    {
        "__typename": "Job",
        "id": "job-1",
        "name": "my-job",
        "jobState": "NAIS_JOB_STATE_RUNNING",
        "team": {"slug": "team-alpha"},
        "teamEnvironment": {
            "gcpProjectID": "my-gcp-project",
            "environment": {"name": "prod"},
        },
        "image": {"name": "ghcr.io/navikt/my-job", "tag": "def456"},
        "deployments": {
            "nodes": [
                {
                    # Only deployment, no status → is_active=False
                    "id": "deploy-2",
                    "createdAt": "2024-06-02T10:00:00Z",
                    "teamSlug": "team-alpha",
                    "environmentName": "prod",
                    "repository": None,
                    "deployerUsername": None,
                    "commitSha": None,
                    "triggerUrl": None,
                    "statuses": {"nodes": []},
                },
            ]
        },
    },
]
