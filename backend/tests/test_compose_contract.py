import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_internal_data_network_loopback_ports_and_no_model_keys():
    config = yaml.safe_load((ROOT / "compose.yaml").read_text())
    assert config["networks"]["backend"]["internal"] is True
    assert config["services"]["frontend"]["networks"] == ["ingress"]
    assert config["services"]["worker"]["networks"] == ["backend"]
    assert config["services"]["api"]["networks"] == ["backend", "ingress"]
    assert set(config["services"]) == {"api", "worker", "migrate", "frontend", "redis", "postgres"}
    for name, service in config["services"].items():
        assert all(mount.startswith("/") for mount in service.get("tmpfs", []))
        assert re.search(r"@sha256:[0-9a-f]{64}$", service["image"]) or service.get("build")
        for port in service.get("ports", []):
            assert port.startswith("127.0.0.1:")
        if name in ("api", "worker", "migrate", "frontend"):
            assert service["read_only"] is True
            assert service["user"] != "root"
            assert service["cap_drop"] == ["ALL"]
        assert not service.get("env_file")
        assert not any("KEY" in key or "TOKEN" in key for key in service.get("environment", {}))
    assert "ports" not in config["services"]["postgres"]
    assert "ports" not in config["services"]["redis"]
    assert config["services"]["api"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"


def test_gpu_overlay_is_opt_in_hardware_only():
    config = yaml.safe_load((ROOT / "compose.gpu.yaml").read_text())
    service = config["services"]["gpu-check"]
    assert service["profiles"] == ["gpu-check"]
    assert service["network_mode"] == "none"
    assert service["gpus"] == "all"
    assert "nvidia-smi" in service["command"]
    assert len(service["command"]) == 3
