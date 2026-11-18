import pytest

from floodcast.core.errors import FloodcastError
from floodcast.core.registries import Registries
from floodcast.core.registry import ComponentManifest, ComponentRegistry


def manifest(name="test", contract="ffw.step/v1"):
    return ComponentManifest(
        component_id=name,
        contract_id=contract,
        implementation_version="1",
        source_revision="revision-1",
    )


def test_registration_is_lazy_and_instances_are_per_execution():
    calls = []
    registry = ComponentRegistry("ffw.step/v1")

    def factory():
        result = object()
        calls.append(result)
        return result

    registry.register(manifest(), factory)
    entry = registry.resolve("test")
    assert not calls
    assert entry.factory() is not entry.factory()
    assert len(calls) == 2


def test_duplicate_does_not_replace_original():
    registry = ComponentRegistry("ffw.step/v1")
    factory = object
    registry.register(manifest(), factory)
    with pytest.raises(FloodcastError, match="Duplicate"):
        registry.register(manifest(), lambda: None)
    assert registry.resolve("test").factory is factory


def test_unknown_component_fails_explicitly():
    with pytest.raises(FloodcastError, match="Unknown"):
        ComponentRegistry("ffw.step/v1").resolve("missing")


@pytest.mark.parametrize("contract", ["ffw.step/v2", "ffw.model-adapter/v1"])
def test_contract_family_and_version_are_checked(contract):
    with pytest.raises(FloodcastError, match="contract mismatch"):
        ComponentRegistry("ffw.step/v1").register(manifest(contract=contract), object)


def test_non_callable_factory_rejected():
    with pytest.raises(FloodcastError, match="callable"):
        ComponentRegistry("ffw.step/v1").register(manifest(), 1)


def test_registries_are_not_global_or_installation_catalogues():
    first, second = Registries(), Registries()
    first.steps.register(manifest(), object)
    assert not second.steps.manifests()
    assert not hasattr(first, "installations")
    assert first.steps.contract_id != first.model_adapters.contract_id


def test_manifest_listing_is_deterministic():
    registry = ComponentRegistry("ffw.step/v1")
    registry.register(manifest("z"), object)
    registry.register(manifest("a"), object)
    assert [item.component_id for item in registry.manifests()] == ["a", "z"]
