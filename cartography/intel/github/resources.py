# GitHub resource names for selective sync.
# These keys are the valid values for --github-requested-syncs.
# None means all resources are synced (default behaviour).
#
# Top-level sub-syncs
# -------------------
# users                  - Org members and enterprise owners (GitHubUser nodes)
# repos                  - Repositories, branch protection rules, rulesets,
#                          collaborators, and dependency manifests (GitHubRepository, …)
# personal_access_tokens - Fine-grained and classic PATs approved for the org
# dependabot_alerts      - All Dependabot alerts for the org (all states)
# teams                  - Teams with repo permissions, members, and child teams
# actions                - Workflows, secrets, variables, and environments
# commits                - Aggregate COMMITTED_TO relationships per (user, repo)
# packages               - Container packages and the full GHCR image pipeline
# supply_chain           - Provenance links between container images and repos
RESOURCE_FUNCTIONS: list[str] = [
    "users",
    "repos",
    "personal_access_tokens",
    "dependabot_alerts",
    "teams",
    "actions",
    "commits",
    "packages",
    "supply_chain",
]
