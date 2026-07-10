# GitHub Module: Incremental Sync — Upstream Contribution Proposal

## Background

Cartography's GitHub intel module performs a full re-fetch of every repository
on every sync run. For organizations with thousands of repositories this
produces prohibitively long runtimes. The following was measured on a navikt
organization with ~6,500 repositories:

| Stage | Duration | % of total |
|---|---|---|
| Dependency graph manifests | 30h 42m | 67% |
| Actions (workflows/secrets/vars/envs) | 10h 55m | 24% |
| Commits | 1h 12m | 3% |
| Other | ~2m | <1% |
| **Total** | **45h 45m** | |

The core problem is that the module treats every repo identically every run:
6,500 repos receive the same API calls whether they were pushed to yesterday
or three years ago. GitHub's GraphQL API already provides a `pushedAt`
timestamp per repository that makes it straightforward to skip repos where
nothing has changed.

---

## What We Implemented

### 1. `pushedAt` on `GitHubRepository` nodes

`pushedAt` is added to the `GITHUB_ORG_REPOS_PAGINATED_GRAPHQL` query and
stored as a `pushedat` property on `GitHubRepository` nodes. It represents
the timestamp of the last push to the repository's default branch. Adding one
field to an already-paginated query costs no extra API quota.

A corresponding `pushedat: PropertyRef` is added to
`GitHubRepositoryNodeProperties`.

### 2. `synced_pushedat` bookmark

After all downstream sync stages (Actions, manifests, commits) complete,
`_write_synced_pushedat()` writes the current `pushedat` value back to every
`GitHubRepository` node as `synced_pushedat`. This bookmark is written at the
very end of the sync — after Actions, manifests and commits have finished — so
it always reflects the *previous* completed run when the next run's skip logic
reads it.

The bookmark is the shared signal used by all downstream stages. No per-stage
bookmarks are needed.

### 3. `--github-incremental-sync` flag

A single opt-in boolean flag (default `False`) that enables all push-based
skip optimizations at once:

**Archived/disabled repos** are excluded from the Actions, commits, and
manifest syncs. A repo that is archived cannot receive new pushes, workflow
changes, or secret updates.

**Dependency graph manifests** are not re-fetched for repos whose current
`pushedat` matches `synced_pushedat`. The nested GraphQL manifest + dependency
pagination is skipped entirely. Existing `DependencyGraphManifest` and
`Dependency` nodes for skipped repos are "touched" — their `lastupdated`
property is refreshed to the current update tag — so the end-of-run stale-tag
`GraphJob` cleanup does not delete them.

**Workflow YAML** is not re-fetched for repos whose `pushedat` matches
`synced_pushedat`. Secrets, variables, and environments are always re-fetched
regardless, since they can change without a push. Existing `GitHubWorkflow`
and `GitHubAction` nodes for skipped repos are touched to survive cleanup.

**Commits** are skipped for repos whose `pushedat` is older than the commit
lookback window (`--github-commit-lookback-days`, default 30 days). If a repo
has had no push in that window, it cannot have any commits in the window.
Repos with no `pushedat` recorded are never skipped.

### 4. `--github-parallel-workers` flag

A separate integer flag (default `1`, sequential) controlling the number of
concurrent workers for per-repo API fetches in the Actions and manifest stages.
Both use `ThreadPoolExecutor` with all Neo4j writes sequenced on the main
thread after each future completes — workers only perform API calls. This
avoids concurrent write contention while still parallelising the dominant
per-repo network I/O.

### 5. `fetch_all` retry fix

A pre-existing bug in `fetch_all`: when GitHub returns a 502 the page size
(`count`) is halved and the call retried. A subsequent successful page at the
reduced size was resetting `retry` to zero, causing persistent 502s at a
degraded page size to loop indefinitely instead of eventually giving up.

The fix tracks the initial `count` and only resets `retry` on success when
`count` has not been degraded. `fetch_all` now correctly returns partial data
after exhausting retries at any page size.

---

## How It Works

### Skip decision

```
repos.sync()
  └─ get() — fetches fresh pushedAt from GitHub GraphQL
  └─ load() — writes pushedat to GitHubRepository nodes
  └─ [all downstream stages run, reading pushedat vs synced_pushedat]
  └─ _write_synced_pushedat() — writes synced_pushedat = pushedat
                                (runs AFTER all stages complete)
```

At the start of each run, the graph has:
- `pushedat` = value from the previous run's `get()` call
- `synced_pushedat` = value written at the end of the previous run

If `pushedat == synced_pushedat`, nothing was pushed between the last repos
fetch and the end of the last full sync. The skip is safe.

After `load()` writes fresh `pushedat`, downstream stages compare the new
value against `synced_pushedat`. Repos with a newer `pushedat` get full API
calls; repos that match are skipped.

### Stale-tag safety

Cartography's cleanup mechanism (`GraphJob`) deletes nodes whose `lastupdated`
does not match the current update tag. When a repo's fetch is skipped, its
existing nodes would otherwise be cleaned up. The solution:

- After collecting the set of skipped repo URLs, a single write query sets
  `lastupdated = $UPDATE_TAG` on all `GitHubWorkflow`, `GitHubAction`,
  `DependencyGraphManifest`, and `Dependency` nodes belonging to those repos.
- This "touch" runs on the main thread before cleanup, costing one Cypher
  write per stage instead of one API call per repo.

---

## Measured Results

Organization: navikt (~6,600 repositories), production Kubernetes cluster,
`--github-parallel-workers 4`.

All figures are from actual production runs with logs verified via `kubectl logs`.

### Runtime comparison: baseline vs run 9 (2026-07-10)

| Stage | Baseline | With flags | Reduction |
|---|---|---|---|
| Dependency graph manifests | 30h 42m | 1h 36m | −95% |
| Actions (workflows/secrets/vars/envs) | 10h 55m | 1h 40m | −85% |
| Commits | 1h 12m | 33m | −54% |
| **Total** | **45h 45m** | **7h 12m** | **−84%** |

The baseline was measured on the same organization in May 2026 with no
performance flags and sequential (1 worker) fetches.

### Skip rates observed in run 9

| Stage | Total repos | Skipped | Skip rate |
|---|---|---|---|
| Archived repos excluded from all syncs | 6,596 | 2,659 | 40.3% |
| Manifest re-fetch skipped (`pushedat` unchanged) | 3,937 | 3,543 | 90.0% |
| Workflow YAML re-fetch skipped (`pushedat` unchanged) | 3,937 | 3,543 | 90.0% |
| Stale commits skipped (no push in 30-day window) | 3,937 | 1,975 | 50.2% |

394 of 3,937 active repos had pushes between the previous run and run 9 and
received full API calls. The remaining 3,543 had unchanged `pushedat` and
were correctly skipped.

---

## Test Coverage

### Integration tests

**`test_sync_github_actions_incremental_skip_preserves_workflows`**
(`tests/integration/cartography/intel/github/test_actions.py`)

Seeds a `GitHubRepository` with `pushedat` and `synced_pushedat` set to the
same value. Runs `actions.sync()` twice with a new update tag on the second
call. Asserts:
- `get_repo_workflows` is called exactly once (skipped on second run)
- `GitHubWorkflow` nodes still exist after the second run (touched, not deleted)
- `lastupdated` on workflow nodes equals the second run's update tag

**`test_get_dep_manifests_for_repos_incremental_skip_preserves_manifests`**
(`tests/integration/cartography/intel/github/test_repos.py`)

Seeds a `GitHubRepository` with `synced_pushedat` matching the repo's
`pushedAt`. Calls `_get_dep_manifests_for_repos()` with a new update tag.
Asserts:
- `_get_repo_dep_manifests` is never called (skipped)
- `DependencyGraphManifest` and `Dependency` nodes are present after the call
- Their `lastupdated` equals the new update tag (touched correctly)

**`test_sync_github_commits_skip_stale_repos`**
(`tests/integration/cartography/intel/github/test_commits.py`)

Sets one repo's `pushedat` to a date well outside the lookback window and
leaves a second repo without any `pushedat`. Asserts that only the second repo
(no `pushedat` recorded, treated as unknown) has its commits API called.

### Unit tests

**`test_fetch_all_raises_after_persistent_502s_at_degraded_page_size`**
(`tests/unit/cartography/intel/github/test_github.py`)

Provides a mock sequence of alternating 502/success responses after the page
size has been halved. Asserts that `fetch_all` eventually exhausts retries
and returns partial data, rather than resetting the retry counter on each
success and looping indefinitely.

**`test_fetch_all_returns_partial_data_after_exhausting_retries`**

Verifies that when retries are exhausted mid-pagination, `fetch_all` returns
whatever data was collected before the failure rather than raising an exception,
allowing the sync to continue with partial data.

---

## Configuration Reference

```
cartography \
  --selected-modules create-indexes,github \
  --github-config-env-var GITHUB_CONFIG \
  --github-incremental-sync \
  --github-parallel-workers 4
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `--github-incremental-sync` | bool | `False` | Enable all push-based skip optimizations |
| `--github-parallel-workers` | int | `1` | Concurrent workers for per-repo API fetches |

Both flags are opt-in and default to the existing behaviour — no changes for
deployments that do not set them.

---

## Files Changed (intended upstream contribution)

| File | Change |
|---|---|
| `cartography/config.py` | Add `github_incremental_sync`, `github_parallel_workers` |
| `cartography/cli.py` | Add `--github-incremental-sync`, `--github-parallel-workers` |
| `cartography/models/github/repos.py` | Add `pushedat: PropertyRef` |
| `cartography/intel/github/repos.py` | Add `pushedAt` to GraphQL query; `_write_synced_pushedat`; manifest skip/touch; parallel manifest workers; `GitHubRepoSyncResult.repo_pushedat_updates` |
| `cartography/intel/github/actions.py` | Parallel workers; archived-repo skip; workflow skip/touch via `synced_pushedat` |
| `cartography/intel/github/commits.py` | Stale-repo skip via `pushedat` vs lookback window |
| `cartography/intel/github/__init__.py` | Wire flags; call `_write_synced_pushedat` after all downstream stages; archived-repo filter on `_get_repos_from_graph` |
| `cartography/intel/github/util.py` | Fix `fetch_all` retry counter reset at degraded page size |
| `tests/integration/cartography/intel/github/test_actions.py` | Incremental skip + touch integration test |
| `tests/integration/cartography/intel/github/test_repos.py` | Manifest skip + touch integration test |
| `tests/integration/cartography/intel/github/test_commits.py` | Stale-skip integration test |
| `tests/unit/cartography/intel/github/test_github.py` | `fetch_all` retry/502 unit tests |
