import pytest

from cartography.intel.github.util import parse_and_validate_github_requested_syncs


def test_parse_and_validate_github_requested_syncs_no_spaces() -> None:
    result = parse_and_validate_github_requested_syncs("users,repos,teams")
    assert result == ["users", "repos", "teams"]


def test_parse_and_validate_github_requested_syncs_with_spaces() -> None:
    result = parse_and_validate_github_requested_syncs("repos, actions, packages")
    assert result == ["repos", "actions", "packages"]


def test_parse_and_validate_github_requested_syncs_all_resources() -> None:
    all_resources = (
        "users,repos,dep_manifests,personal_access_tokens,dependabot_alerts,"
        "teams,actions,commits,packages,supply_chain"
    )
    result = parse_and_validate_github_requested_syncs(all_resources)
    assert result == [
        "users",
        "repos",
        "dep_manifests",
        "personal_access_tokens",
        "dependabot_alerts",
        "teams",
        "actions",
        "commits",
        "packages",
        "supply_chain",
    ]


def test_parse_and_validate_github_requested_syncs_unknown_resource() -> None:
    with pytest.raises(ValueError):
        parse_and_validate_github_requested_syncs("users,thisdoesnotexist,repos")


def test_parse_and_validate_github_requested_syncs_garbage() -> None:
    with pytest.raises(ValueError):
        parse_and_validate_github_requested_syncs("#@$GARBAGE,KDFJHW#@,")
