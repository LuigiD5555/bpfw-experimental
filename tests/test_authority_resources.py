from bpfw.authority.resources import AuthorityResourceRegistry


def test_authority_registry_matches_core_resources() -> None:
    registry = AuthorityResourceRegistry()
    resources = registry.list_resources()
    assert any(resource.path == "blueprint.yaml" for resource in resources)
    assert any(resource.path == "architecture.yaml" for resource in resources)
    assert any(resource.path == ".bpfw/manifest.json" for resource in resources)


def test_is_authority_path_supports_file_and_prefix_targets() -> None:
    registry = AuthorityResourceRegistry()
    assert registry.is_authority_path("pyproject.toml")
    assert registry.is_authority_path("src/bpfw/core/registry.py")
    assert registry.is_authority_path(".bpfw/access_grants/grant-001.json")
    assert not registry.is_authority_path("src/application/query/query_service.py")


def test_resolve_by_path_for_default_resource() -> None:
    registry = AuthorityResourceRegistry()
    resolved = registry.resolve_by_path("blueprint.yaml")
    assert resolved is not None
    assert resolved.resource_id == "project_blueprint"
