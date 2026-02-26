# Checkpoint 002 — NAIS Intel Module: Complete Implementation

## Status: COMPLETE — all 7 phases shipped and tested

This checkpoint documents the full state of the NAIS Cartography intel module as of the end of session `e57e6ab4`. The module is fully functional and ready for a live test against the NAIS API.

---

## What Was Built

### Goal
Ingest NAIS platform data (teams, members, workloads, deployments) into the Cartography Neo4j graph and wire it up to existing nodes from GitHub, Entra ID, and Kubernetes modules so you can answer questions like:
- Who is responsible for this pod in production?
- What GitHub repo does this pod come from?
- What NAIS teams does a GitHub user belong to?

### Graph model overview

```
NaisTenant
  └─[:RESOURCE]──► NaisTeam
  └─[:RESOURCE]──► NaisMember
  └─[:RESOURCE]──► NaisApp
  └─[:RESOURCE]──► NaisDeployment

NaisTeam ──[:HAS_MEMBER]──────► NaisMember
NaisTeam ──[:HAS_APP]──────────► NaisApp
NaisTeam ──[:HAS_DEPLOYMENT]───► NaisDeployment
NaisTeam ──[:HAS_ENTRA_GROUP]──► EntraGroup         (cross-module, requires Entra)
NaisTeam ──[:HAS_GITHUB_TEAM]──► GitHubTeam         (cross-module, requires GitHub)

NaisApp  ──[:RUNS_IN]──────────► KubernetesNamespace (cross-module, requires k8s)

NaisDeployment ──[:DEPLOYED_FROM]──► GitHubRepository (cross-module, requires GitHub)

[analysis job] NaisMember ──[:RESPONSIBLE_FOR]──► NaisApp (via team membership)
[analysis job] KubernetesPod ──[:DEPLOYED_FROM]──► GitHubRepository (via namespace → app → deployment)
```

---

## All Files

### New files

| File | Purpose |
|------|---------|
| `cartography/intel/nais/__init__.py` | Entry point: `start_nais_ingestion()` |
| `cartography/intel/nais/client.py` | `NaisGraphQLClient` — Bearer auth, pagination |
| `cartography/intel/nais/teams.py` | get / transform / load / cleanup for teams + members |
| `cartography/intel/nais/workloads.py` | get / transform / load / cleanup for NaisApp + NaisDeployment |
| `cartography/models/nais/__init__.py` | Package marker |
| `cartography/models/nais/tenant.py` | `NaisTenantSchema` |
| `cartography/models/nais/team.py` | `NaisTeamSchema`, `NaisMemberSchema`, all rel schemas |
| `cartography/models/nais/workload.py` | `NaisAppSchema`, `NaisDeploymentSchema`, all rel schemas |
| `cartography/data/jobs/analysis/nais/nais_ownership.json` | Post-ingest analysis jobs |
| `tests/data/nais/__init__.py` | Package marker |
| `tests/data/nais/teams.py` | Mock team + member GraphQL response fixtures |
| `tests/data/nais/workloads.py` | Mock workload + deployment GraphQL response fixtures |
| `tests/integration/cartography/intel/nais/__init__.py` | Package marker |
| `tests/integration/cartography/intel/nais/test_teams.py` | 2 integration tests |
| `tests/integration/cartography/intel/nais/test_workloads.py` | 3 integration tests |
| `docs/root/modules/nais/index.md` | Module docs index |
| `docs/root/modules/nais/config.md` | Configuration guide |
| `docs/root/modules/nais/schema.md` | Schema reference + example queries |

### Modified files

| File | Change |
|------|--------|
| `cartography/sync.py` | Added `import cartography.intel.nais` and `"nais": cartography.intel.nais.start_nais_ingestion` in `TOP_LEVEL_MODULES` |
| `cartography/config.py` | Added `nais_api_key: str` and `nais_base_url: str` params |
| `cartography/cli.py` | Added `PANEL_NAIS`, `--nais-api-key-env-var`, `--nais-base-url` CLI options |
| `cartography/models/ontology/mapping/data/useraccounts.py` | Registered `NaisMember` in `USERACCOUNTS_ONTOLOGY_MAPPING` with `email` (required) and `name→fullname` |
| `README.md` | Added NAIS to the supported platforms list |

---

## Key Technical Decisions

### Tenant = base URL
`NaisTenant.id` is the NAIS Console GraphQL endpoint URL (e.g. `https://console.nav.cloud.nais.io/query`). This matches how Cartography uses tenant anchors in other modules and doubles as a stable, human-readable identifier. The `common_job_parameters` dict uses key `TENANT_ID` for this value, and the schema kwarg is `NAIS_TENANT_ID`.

### Team slug = Kubernetes namespace
`NaisTeam.slug` is identical to the Kubernetes namespace name that NAIS uses for all workloads owned by that team. The `NaisAppToKubernetesNamespaceRel` matches on `KubernetesNamespace.name = team_slug`. This is the critical bridge to Kubernetes.

### Cross-module relationship matching
All cross-module relationships are defined as `OtherRelationships` in the schema. If the target node doesn't exist (because the other module hasn't synced), no relationship is created and no error is raised — Cartography handles this gracefully.

| Relationship | Match field | Target module |
|---|---|---|
| `NaisTeam → EntraGroup` | `EntraGroup.id = entra_group_id` | Entra |
| `NaisTeam → GitHubTeam` | `GitHubTeam.name = github_team_slug` | GitHub |
| `NaisApp → KubernetesNamespace` | `KubernetesNamespace.name = team_slug` | Kubernetes |
| `NaisDeployment → GitHubRepository` | `GitHubRepository.name = repository` | GitHub |

Note: `GitHubRepository.name` is the `"org/repo"` string (e.g. `"navikt/my-app"`), **not** the URL-based `id`. The `repository` field from the NAIS deployments API is already in this format.

Note: `GitHubTeam.name` is set from `team["slug"]` in `cartography/intel/github/teams.py:108` — not from the team `name` field.

### NaisMember has UserAccount label
`NaisMemberSchema` uses `ExtraNodeLabels(["UserAccount"])` which opts it into Cartography's ontology cross-module user correlation system. The join key is `email`. This means `NaisMember` nodes are automatically linked to `EntraUser`, `GitHubUser`, `GCPUser`, etc. nodes that share the same email address — once the ontology analysis jobs run.

To find NAIS teams for a GitHub user, two paths work:
1. Via GitHubTeam: `(GitHubUser)-[:MEMBER]->(GitHubTeam)<-[:HAS_GITHUB_TEAM]-(NaisTeam)`
2. Via email: `MATCH (gu:GitHubUser {email:$e}),(m:NaisMember {email:$e})<-[:HAS_MEMBER]-(t:NaisTeam)`

### Analysis jobs
`cartography/data/jobs/analysis/nais/nais_ownership.json` runs two post-ingest enrichment queries:
1. `RESPONSIBLE_FOR`: `(NaisMember)-[:RESPONSIBLE_FOR]->(NaisApp)` — written for all members of the team that owns each app.
2. `DEPLOYED_FROM` shortcut: `(KubernetesPod)-[:DEPLOYED_FROM]->(GitHubRepository)` — written by traversing pod → namespace → NaisApp → NaisDeployment → GitHubRepository.

---

## GraphQL Queries Used

Teams (paginated):
```graphql
query GetTeams($first: Int!, $cursor: Cursor) {
  teams(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id slug purpose slackChannel lastSuccessfulSync
      externalResources {
        entraIDGroup { groupID }
        gitHubTeam { slug }
        googleGroup { email }
      }
      members(first: 500) {
        nodes { role user { id email name externalID } }
      }
    }
  }
}
```

Workloads per environment (paginated, inline fragments for Application/Job):
```graphql
query GetWorkloads($env: String!, $first: Int!, $cursor: Cursor) {
  environment(name: $env) {
    workloads(first: $first, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        ... on Application { __typename id name state team { slug }
          teamEnvironment { gcpProjectID environment { name } }
          image { name tag } ingresses { host } }
        ... on Job { __typename id name state team { slug }
          teamEnvironment { gcpProjectID environment { name } }
          image { name tag } }
      }
    }
  }
}
```

Deployments (paginated):
```graphql
query GetDeployments($first: Int!, $cursor: Cursor) {
  deployments(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes { id createdAt teamSlug environmentName repository
            deployerUsername commitSha triggerUrl }
  }
}
```

---

## Running the Tests

```bash
# All 5 pass (no live API or Neo4j instance needed)
uv run pytest tests/integration/cartography/intel/nais/ -v
```

## Running Against Live NAIS API

```bash
docker compose up neo4j -d
export NAIS_API_KEY=<your-key>

uv run cartography \
  --neo4j-uri bolt://localhost:7687 \
  --selected-modules nais \
  --nais-api-key-env-var NAIS_API_KEY \
  --nais-base-url https://console.nav.cloud.nais.io/query \
  -v

# Explore in Neo4j browser at http://localhost:7474
```

---

## Known Gaps / Future Work

### Not yet implemented (good next tasks)
- **NaisSecret / ExternalSecret nodes** — NAIS teams can have secrets attached; useful for secret sprawl analysis.
- **NaisJobRun nodes** — individual executions of `Job` workloads with timestamps and status.
- **Google Workspace group link** — `NaisTeam.google_group_email` is stored on the node but no `OtherRelationships` entry links it to a `GoogleWorkspaceGroup` node. The match would be `GoogleWorkspaceGroup.email = google_group_email`.
- **GCP project link** — `NaisApp.gcp_project_id` is stored but not linked to a `GCPProject` node. Match: `GCPProject.id = gcp_project_id`.
- **Container image provenance** — `NaisApp.image_name` + `image_tag` could be linked to ECR/GCR/GHCR image nodes.
- **Environment cost/quota data** — NAIS `TeamEnvironment` exposes resource requests/limits; could become properties on `NaisApp`.

### Verified assumptions to watch
- `GitHubTeam.name` is set from `team["slug"]` in `cartography/intel/github/teams.py:108`. If this changes, `NaisTeamToGitHubTeamRel` will silently stop matching.
- `KubernetesNamespace.name` must equal the NAIS team slug exactly. If a team has separate namespaces per environment (future NAIS feature), the match would need `cluster_name + namespace` disambiguation.
- The `deployments` root query on the NAIS API returns ALL deployments across all teams. Consider filtering by time range if this becomes too large.

### Authentication note
The client sends `Authorization: Bearer <api_key>`. Verify this is the correct header format for your NAIS Console API version — it was assumed from common GraphQL API patterns.
