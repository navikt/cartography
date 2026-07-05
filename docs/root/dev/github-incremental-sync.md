# GitHub Module: Incremental Sync

This document describes the opt-in performance flags for the GitHub intel
module, designed for large GitHub organizations with thousands of repositories.

## How it works

### `pushedat` and `synced_pushedat`

Every `GitHubRepository` node has two properties that drive skip decisions:

- **`pushedat`**: the timestamp of the last push to the repo, fetched from
  GitHub's GraphQL API as part of the standard repos sync. Costs no extra
  API quota — one additional field in an already-paginated query.

- **`synced_pushedat`**: a bookmark written to every repo after each
  successful repos sync, recording the `pushedat` value seen at that time.
  All downstream stages (Actions, manifests, commits) compare the repo's
  current `pushedat` against this bookmark. If they match, the repo has not
  been pushed since the last repos sync and can be skipped.

Because `synced_pushedat` is written centrally by repos sync for every repo,
all incremental-skip flags benefit from the first run — there is no separate
warm-up pass.

## Flags

All flags default to `False` and are opt-in.

### `--github-skip-archived-repo-manifests`

Skips the dependency graph manifest fetch for archived and disabled repos.

### `--github-skip-archived-actions-sync`

Skips the Actions sync (workflows, secrets, variables, environments) for
archived and disabled repos.

### `--github-skip-archived-commits-sync`

Skips the commits sync for archived and disabled repos.

### `--github-skip-stale-commits-sync`

Skips the per-repo commit-history GraphQL fetch for repos whose `pushedat`
is older than the commit lookback window (`--github-commit-lookback-days`,
default 30 days). Repos with no `pushedat` on record are never skipped.

### `--github-incremental-actions-workflow-sync`

Skips the per-repo workflow YAML fetch and parse for repos whose `pushedat`
matches `synced_pushedat`. Secrets, variables, and environments are always
fetched regardless — they can change without a push.

When a repo's workflow fetch is skipped, its existing `GitHubWorkflow` and
`GitHubAction` nodes are touched (their `lastupdated` refreshed to the
current update tag) so the end-of-run stale-tag cleanup does not delete them.

### `--github-incremental-dep-manifest-sync`

Skips the nested GraphQL manifest and dependency pagination for repos whose
`pushedat` matches `synced_pushedat`. When skipped, existing
`DependencyGraphManifest` and `Dependency` nodes are touched to survive
stale-tag cleanup.

### `--github-parallel-workers N`

Number of parallel workers for per-repo API fetches (Actions, manifests,
collaborators). Default `1` (sequential). Each worker consumes GitHub API
quota independently — increase conservatively. In production, `4` works well.

When all workers exhaust the rate limit at the same time, they all sleep
until the same reset window — the wall-clock sleep cost does not multiply
with worker count.

## Recommended command

```
cartography \
  --selected-modules create-indexes,github \
  --github-config-env-var GITHUB_CONFIG \
  --github-skip-archived-repo-manifests \
  --github-skip-archived-actions-sync \
  --github-skip-archived-commits-sync \
  --github-skip-stale-commits-sync \
  --github-incremental-actions-workflow-sync \
  --github-incremental-dep-manifest-sync \
  --github-parallel-workers 4
```

## Measured results (navikt org, ~6,500 repos)

| Run | Manifests | Actions | Commits | Total |
|---|---|---|---|---|
| No flags | 30h 42m | 10h 55m | 1h 12m | **45h 45m** |
| Flags, no manifests, first run | — | 3h 44m | 59m | 7h 35m |
| Flags, no manifests, steady state | — | 1h 42m | 30m | **4h 45m** |
| All flags, first run with manifests | 7h 22m | 1h 36m | 32m | 12h 11m |
| All flags, steady state | **3m 56s** | 1h 42m | 28m | **4h 49m** |

Steady-state reduction: **89% vs. the no-flags baseline**.

Key drivers:
- **Archived-repo skip**: 2,649 of 6,579 repos (40%) excluded from Actions
  and manifests entirely.
- **Incremental workflow skip**: 86–95% of active repos skipped each run
  once bookmarks are populated.
- **Manifests incremental skip**: reduces a 7h 22m first-run to under 4
  minutes in steady state.
- **Commits stale skip**: ~50% of active repos have no push in 30 days and
  are skipped entirely.
- **Parallel workers**: 4× concurrency reduces the manifests stage from
  ~17s/repo sequential to ~6.6s/repo with parallel fetches.

## Data quality queries

### Manifests fetched vs served from cache (last run)

Replace `$UPDATE_TAG` with the update tag from the last run
(`MATCH (s:SyncMetadata) RETURN s.lastupdated LIMIT 1`).

```cypher
MATCH (r:GitHubRepository)-[:HAS_MANIFEST]->(m:DependencyGraphManifest)
WITH
  count(m)                                                          AS total_manifests,
  count(CASE WHEN m.lastupdated = $UPDATE_TAG THEN 1 END)          AS fetched_this_run,
  count(CASE WHEN m.lastupdated < $UPDATE_TAG THEN 1 END)          AS served_from_cache,
  count(DISTINCT r)                                                 AS repos_with_manifests,
  count(DISTINCT CASE WHEN m.lastupdated = $UPDATE_TAG THEN r END) AS repos_refetched,
  count(DISTINCT CASE WHEN m.lastupdated < $UPDATE_TAG THEN r END) AS repos_from_cache
RETURN
  total_manifests,
  fetched_this_run,
  served_from_cache,
  repos_with_manifests,
  repos_refetched,
  repos_from_cache,
  round(100.0 * served_from_cache / total_manifests, 1) AS pct_from_cache
```

### Repos by push recency (commit lookback window)

```cypher
WITH datetime() - duration('P30D') AS cutoff
MATCH (r:GitHubRepository)
WHERE r.archived = false AND r.disabled = false
WITH
  cutoff,
  count(r)                                                                   AS total_active_repos,
  count(CASE WHEN r.pushedat IS NULL THEN 1 END)                            AS no_pushedat_recorded,
  count(CASE WHEN r.pushedat IS NOT NULL
             AND datetime(r.pushedat) >= cutoff THEN 1 END)                 AS pushed_within_30d,
  count(CASE WHEN r.pushedat IS NOT NULL
             AND datetime(r.pushedat) < cutoff THEN 1 END)                  AS not_pushed_in_30d
RETURN
  total_active_repos,
  no_pushedat_recorded,
  pushed_within_30d,
  not_pushed_in_30d,
  round(100.0 * pushed_within_30d / total_active_repos, 1) AS pct_active,
  round(100.0 * not_pushed_in_30d  / total_active_repos, 1) AS pct_skipped_commits
```

### Bookmark coverage — repos to be skipped on next run

```cypher
MATCH (r:GitHubRepository)
WHERE r.archived = false
RETURN
  count(r)                                                    AS total_non_archived,
  count(r.synced_pushedat)                                    AS have_bookmark,
  count(CASE WHEN r.synced_pushedat = r.pushedat THEN 1 END) AS will_skip_next_run,
  count(CASE WHEN r.synced_pushedat <> r.pushedat THEN 1 END) AS will_refetch_next_run
```
