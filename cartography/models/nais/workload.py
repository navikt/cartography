from dataclasses import dataclass

from cartography.models.core.common import PropertyRef
from cartography.models.core.nodes import CartographyNodeProperties
from cartography.models.core.nodes import CartographyNodeSchema
from cartography.models.core.relationships import CartographyRelProperties
from cartography.models.core.relationships import CartographyRelSchema
from cartography.models.core.relationships import LinkDirection
from cartography.models.core.relationships import make_target_node_matcher
from cartography.models.core.relationships import OtherRelationships
from cartography.models.core.relationships import TargetNodeMatcher


# ---------------------------------------------------------------------------
# NaisApp (Application + Job workloads)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NaisAppNodeProperties(CartographyNodeProperties):
    id: PropertyRef = PropertyRef("id")
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)
    name: PropertyRef = PropertyRef("name", extra_index=True)
    workload_type: PropertyRef = PropertyRef("workload_type")  # "Application" or "Job"
    team_slug: PropertyRef = PropertyRef("team_slug", extra_index=True)
    environment: PropertyRef = PropertyRef("environment", extra_index=True)
    gcp_project_id: PropertyRef = PropertyRef("gcp_project_id")
    image_name: PropertyRef = PropertyRef("image_name")
    image_tag: PropertyRef = PropertyRef("image_tag")
    state: PropertyRef = PropertyRef("state")
    ingresses: PropertyRef = PropertyRef("ingresses")


@dataclass(frozen=True)
class NaisAppToTenantRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisApp)<-[:RESOURCE]-(:NaisTenant)
class NaisAppToTenantRel(CartographyRelSchema):
    target_node_label: str = "NaisTenant"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("NAIS_TENANT_ID", set_in_kwargs=True)},
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "RESOURCE"
    properties: NaisAppToTenantRelProperties = NaisAppToTenantRelProperties()


@dataclass(frozen=True)
class NaisAppToTeamRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisTeam)-[:HAS_APP]->(:NaisApp)
class NaisAppToTeamRel(CartographyRelSchema):
    target_node_label: str = "NaisTeam"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"slug": PropertyRef("team_slug")},
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "HAS_APP"
    properties: NaisAppToTeamRelProperties = NaisAppToTeamRelProperties()


@dataclass(frozen=True)
class NaisAppToKubernetesNamespaceRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisApp)-[:RUNS_IN]->(:KubernetesNamespace)
# Matched by namespace.name = team slug (NAIS convention)
class NaisAppToKubernetesNamespaceRel(CartographyRelSchema):
    target_node_label: str = "KubernetesNamespace"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"name": PropertyRef("team_slug")},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "RUNS_IN"
    properties: NaisAppToKubernetesNamespaceRelProperties = (
        NaisAppToKubernetesNamespaceRelProperties()
    )


@dataclass(frozen=True)
class NaisAppSchema(CartographyNodeSchema):
    label: str = "NaisApp"
    properties: NaisAppNodeProperties = NaisAppNodeProperties()
    sub_resource_relationship: NaisAppToTenantRel = NaisAppToTenantRel()
    other_relationships: OtherRelationships = OtherRelationships(
        [
            NaisAppToTeamRel(),
            NaisAppToKubernetesNamespaceRel(),
        ]
    )


# ---------------------------------------------------------------------------
# NaisDeployment  (the GitHub→NAIS event link)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NaisDeploymentNodeProperties(CartographyNodeProperties):
    id: PropertyRef = PropertyRef("id")
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)
    created_at: PropertyRef = PropertyRef("created_at")
    team_slug: PropertyRef = PropertyRef("team_slug", extra_index=True)
    environment_name: PropertyRef = PropertyRef("environment_name")
    repository: PropertyRef = PropertyRef("repository", extra_index=True)
    deployer_username: PropertyRef = PropertyRef("deployer_username")
    commit_sha: PropertyRef = PropertyRef("commit_sha")
    trigger_url: PropertyRef = PropertyRef("trigger_url")


@dataclass(frozen=True)
class NaisDeploymentToTenantRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisDeployment)<-[:RESOURCE]-(:NaisTenant)
class NaisDeploymentToTenantRel(CartographyRelSchema):
    target_node_label: str = "NaisTenant"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("NAIS_TENANT_ID", set_in_kwargs=True)},
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "RESOURCE"
    properties: NaisDeploymentToTenantRelProperties = NaisDeploymentToTenantRelProperties()


@dataclass(frozen=True)
class NaisDeploymentToTeamRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisTeam)-[:HAS_DEPLOYMENT]->(:NaisDeployment)
class NaisDeploymentToTeamRel(CartographyRelSchema):
    target_node_label: str = "NaisTeam"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"slug": PropertyRef("team_slug")},
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "HAS_DEPLOYMENT"
    properties: NaisDeploymentToTeamRelProperties = NaisDeploymentToTeamRelProperties()


@dataclass(frozen=True)
class NaisDeploymentToGitHubRepoRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisDeployment)-[:DEPLOYED_FROM]->(:GitHubRepository)
# Matched via deployment.repository = "navikt/my-app" against GitHubRepository.name
class NaisDeploymentToGitHubRepoRel(CartographyRelSchema):
    target_node_label: str = "GitHubRepository"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"name": PropertyRef("repository")},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "DEPLOYED_FROM"
    properties: NaisDeploymentToGitHubRepoRelProperties = (
        NaisDeploymentToGitHubRepoRelProperties()
    )


@dataclass(frozen=True)
class NaisDeploymentSchema(CartographyNodeSchema):
    label: str = "NaisDeployment"
    properties: NaisDeploymentNodeProperties = NaisDeploymentNodeProperties()
    sub_resource_relationship: NaisDeploymentToTenantRel = NaisDeploymentToTenantRel()
    other_relationships: OtherRelationships = OtherRelationships(
        [
            NaisDeploymentToTeamRel(),
            NaisDeploymentToGitHubRepoRel(),
        ]
    )
