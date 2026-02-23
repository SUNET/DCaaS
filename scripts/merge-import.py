#!/usr/bin/env python3
"""Merge a YAML file (device names + passwords) with Kea reservations JSON.

Usage:
    ./scripts/merge-import.py servers.yaml bmc-reservations.json > import.json

The YAML file should contain entries like:
    - device_name: ra07u01
      ipmi_password: secret123
      bmc_mac:
      ipmi_ip:

The Kea JSON file contains entries like:
    { "hostname": "dcoa-ra07u01.bmc.platform.sunet.se",
      "hw-address": "3c:ec:ef:...", "ip-address": "10.16.28.27" }

Output is the merged JSON array ready for POST /api/v1/servers/import.
"""

import json
import sys

import yaml


def build_lookup(reservations: list[dict]) -> dict[str, dict]:
    """Build a lookup from short device name to reservation data."""
    lookup = {}
    for r in reservations:
        # "dcoa-ra07u01.bmc.platform.sunet.se" -> "dcoa-ra07u01"
        short = r["hostname"].split(".")[0]
        lookup[short] = {
            "bmc_mac": r["hw-address"].replace(":", "").upper(),
            "ipmi_ip": r["ip-address"],
        }
    return lookup


def merge(yaml_entries: list[dict], reservations: list[dict]) -> list[dict]:
    lookup = build_lookup(reservations)
    results = []
    missing = []

    for entry in yaml_entries:
        name = entry["device_name"]
        # Try matching as-is first, then with common prefixes
        match = lookup.get(name)
        if not match:
            for prefix in ("dcoa-", "tug-"):
                match = lookup.get(f"{prefix}{name}")
                if match:
                    name = f"{prefix}{name}"
                    break

        if not match:
            missing.append(entry["device_name"])
            continue

        # Use YAML values if present, otherwise fill from Kea
        password = entry.get("ipmi_password") or entry.get("impi_password") or ""
        results.append({
            "device_name": name,
            "bmc_mac": entry.get("bmc_mac") or match["bmc_mac"],
            "ipmi_password": password,
            "ipmi_ip": entry.get("ipmi_ip") or match["ipmi_ip"],
        })

    if missing:
        print(
            f"WARNING: {len(missing)} devices not found in reservations: "
            + ", ".join(missing),
            file=sys.stderr,
        )

    return results


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <servers.yaml> <reservations.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        yaml_entries = yaml.safe_load(f)

    with open(sys.argv[2]) as f:
        reservations = json.load(f)

    merged = merge(yaml_entries, reservations)
    json.dump(merged, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
