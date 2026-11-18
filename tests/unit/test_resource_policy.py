"""Guard live caps, rollback and the boundary excluding monitoring."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture
def policy_module(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "resource_policy_test", SCRIPTS / "apply_resource_policy.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def policy(policy_module):
    return policy_module.load_policy(
        SCRIPTS.parent / "config/production-resource-policy.json"
    )


def container():
    return {
        "Id": "original",
        "Image": "sha256:unchanged",
        "RestartCount": 0,
        "Config": {"Env": ["TOKEN=private"]},
        "HostConfig": {
            "Memory": 0,
            "MemorySwap": 0,
            "NanoCpus": 0,
            "PidsLimit": None,
        },
        "Mounts": [],
        "NetworkSettings": {"Networks": {}},
        "State": {
            "Status": "running",
            "StartedAt": "same",
            "Pid": 123,
            "OOMKilled": False,
            "Health": {"Status": "healthy"},
        },
    }


def test_policy_fits_audited_host_and_excludes_alerts(policy_module, policy):
    assert sum(x["memory_mib"] for x in policy["services"].values()) == 12288
    assert not {"prometheus", "meta_token_monitor", "alertmanager"} & (
        policy_module.SERVICES
    )
    assert policy["logging"]["options"] == {"max-size": "20m", "max-file": "5"}


@pytest.mark.parametrize("change", ["scope", "headroom", "reserve", "logging"])
def test_invalid_policy_fails_closed(policy_module, policy, tmp_path, change):
    if change == "scope":
        policy["services"]["prometheus"] = policy["services"].pop("app")
    elif change == "headroom":
        policy["peak_headroom_percent"] = 100
    elif change == "reserve":
        policy["minimum_host_reserve_mib"] = 0
    else:
        policy["logging"]["options"]["max-file"] = "0"
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    with pytest.raises(ValueError):
        policy_module.load_policy(path)


def test_existing_stricter_limits_are_preserved(policy_module):
    current = container()
    current["HostConfig"].update(
        Memory=64 * 1024**2, NanoCpus=100000000, PidsLimit=32
    )
    limits = policy_module.proposed_limits(
        current, {"memory_mib": 512, "cpus": 2, "pids": 256}
    )
    assert limits == {
        "Memory": 64 * 1024**2,
        "MemorySwap": 64 * 1024**2,
        "NanoCpus": 100000000,
        "PidsLimit": 32,
    }


@pytest.mark.parametrize("failure", ["peak", "pids", "budget", "health"])
def test_preflight_prevents_unsafe_updates(policy_module, policy, failure):
    containers = {s: container() for s in policy_module.SERVICES}
    samples = {
        s: {"current": 1024, "peak": 1024, "pids": 1} for s in containers
    }
    host_memory = 16 * 1024**3
    if failure == "peak":
        samples["app"]["peak"] = 700 * 1024**2
    elif failure == "pids":
        samples["app"]["pids"] = 200
    elif failure == "budget":
        host_memory = 14 * 1024**3
    else:
        containers["app"]["State"]["Health"]["Status"] = "unhealthy"
    with pytest.raises(RuntimeError):
        policy_module.plan(policy, containers, host_memory, samples)


def test_rollback_restores_full_host_capacity_for_unlimited(policy_module):
    result = policy_module.rollback_limits(container(), 16 * 1024**3, 4)
    assert result == {
        "Memory": 16 * 1024**3,
        "MemorySwap": -1,
        "NanoCpus": 4000000000,
        "PidsLimit": -1,
    }


def test_rollback_preserves_previous_bounded_values(policy_module):
    current = container()
    current["HostConfig"].update(
        Memory=128, MemorySwap=256, NanoCpus=500000000, PidsLimit=64
    )
    assert policy_module.rollback_limits(current, 10000, 4) == {
        k: current["HostConfig"][k] for k in policy_module.RESOURCE_FIELDS
    }


@pytest.mark.parametrize("failure", ["restart", "replace", "env", "oom"])
def test_verification_detects_unexpected_effects(
    policy_module, monkeypatch, failure
):
    before = container()
    after = copy.deepcopy(before)
    sample = {"events": {"oom": "0"}}
    if failure == "restart":
        after["RestartCount"] += 1
    elif failure == "replace":
        after["Id"] = "another"
    elif failure == "env":
        after["Config"]["Env"] = ["TOKEN=changed"]
    else:
        sample = {"events": {"oom": "1"}}
    monkeypatch.setattr(policy_module, "cgroup_sample", lambda c: sample)
    with pytest.raises(RuntimeError):
        policy_module.verify_in_place(
            before, after, {}, {"events": {"oom": "0"}}
        )


def test_partial_update_failure_rolls_back_in_reverse_including_failed_call(
    policy_module,
    monkeypatch,
):
    containers = {s: container() for s in ("app", "app_2")}
    for service, item in containers.items():
        item["Id"] = service
    calls = []

    def update(identifier, limits):
        calls.append((identifier, limits))
        if len(calls) == 2:
            raise RuntimeError("Partial Docker update")

    monkeypatch.setattr(policy_module, "update", update)
    monkeypatch.setattr(policy_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(policy_module, "verify_in_place", lambda *a: None)
    monkeypatch.setattr(policy_module, "cgroup_sample", lambda c: {})
    monkeypatch.setattr(policy_module, "check_headroom", lambda *a: None)
    monkeypatch.setattr(
        policy_module.release, "inspect", lambda name: containers[name]
    )
    with pytest.raises(RuntimeError, match="Partial Docker"):
        policy_module.apply_limits(
            containers,
            {"app": {}, "app_2": {}},
            {"app": {}, "app_2": {}},
            10000,
            4,
        )
    assert [x[0] for x in calls] == ["app", "app_2", "app_2", "app"]
    assert calls[-1][1]["Memory"] == 10000


def test_snapshot_pins_docker_update_over_stale_compose(policy_module):
    current = container()
    current["HostConfig"].update(
        Memory=768 * 1024**2,
        MemorySwap=768 * 1024**2,
        NanoCpus=1500000000,
        PidsLimit=256,
    )
    settings = {
        "mem_limit": "100m",
        "cpus": 0.25,
        "deploy": {
            "resources": {
                "limits": {"memory": "100m", "cpus": "0.25", "pids": 10},
                "reservations": {
                    "memory": "10m",
                    "devices": [{"capabilities": ["gpu"]}],
                },
            }
        },
    }
    policy_module.release.pin_resources(settings, current)
    assert settings["mem_limit"] == str(768 * 1024**2)
    assert settings["cpus"] == 1.5
    assert settings["pids_limit"] == 256
    assert settings["deploy"]["resources"] == {
        "reservations": {"devices": [{"capabilities": ["gpu"]}]}
    }
    assert "mem_reservation" not in settings


def test_rotation_only_replaces_app_replicas_with_their_own_images(
    policy_module,
    monkeypatch,
    tmp_path,
    policy,
):
    containers = {s: container() for s in policy_module.SERVICES}
    for service, current in containers.items():
        current["Image"] = "sha256:" + service
    snapshot = {
        "services": {s: {"image": c["Image"]} for s, c in containers.items()}
    }
    writes = []
    calls = []
    monkeypatch.setattr(
        policy_module.release,
        "write_snapshot",
        lambda path, value: writes.append(copy.deepcopy(value)),
    )
    monkeypatch.setattr(
        policy_module.release,
        "deploy_services",
        lambda *args: calls.append(args),
    )
    policy_module.rotate_replicas(
        tmp_path, containers, snapshot, policy["logging"]
    )
    assert [call[1] for call in calls] == [["app"], ["app_2"]]
    assert [call[3] for call in calls] == ["sha256:app", "sha256:app_2"]
    for service in policy_module.SERVICES - {"app", "app_2"}:
        assert writes[0]["services"][service] == snapshot["services"][service]
    assert "logging" not in snapshot["services"]["app"]


def test_unverified_snapshot_cannot_advance_current_pointer(
    policy_module,
    policy,
    tmp_path,
):
    (tmp_path / "compose.json").write_text(
        json.dumps({"services": {"app": {}}})
    )
    with pytest.raises(RuntimeError, match="differ"):
        policy_module.publish(tmp_path, {"services": {}}, policy, "apply")
    assert not (tmp_path / "policy-operation.json").exists()
