# DCaaS — Server Onboarding System

Automates bare-metal server onboarding into a Kubernetes cluster. Scan a barcode, confirm the rack location, press go — the system handles Netbox registration, credential storage, DHCP reservation, and Ironic/Metal3 node creation.

## Architecture

```
┌─────────────────┐         ┌──────────────────────────┐
│   PWA (mobile)   │  HTTPS  │   Onboarding API Server  │
│  barcode scanner │────────▶│   (FastAPI, K8s)         │
│                  │◀────────│                          │
└─────────────────┘         └──────────┬───────────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
               ┌────▼────┐     ┌──────▼─────┐    ┌──────▼──────┐
               │ Netbox   │     │  OpenBao   │    │   Metal3    │
               │ (DCIM)   │     │ (secrets)  │    │  (provision)│
               └──────────┘     └────────────┘    └─────────────┘
```

## Components

### API Server (`server/`)

Python FastAPI application that orchestrates the registration workflow:

1. Creates device + BMC interface in **Netbox**
2. Stores BMC credentials in **OpenBao** (Vault-compatible)
3. Allocates BMC IP from Netbox IPAM and pushes DHCP reservation to **Kea**
4. Creates `BareMetalHost` CRD + BMC Secret in **Metal3**

### PWA (`web/`)

Progressive Web App with barcode scanning for mobile use:

- Two-step barcode scan: BMC MAC address + BMC password
- Location form: datacenter, rack row, rack, U position, device type, role
- Remembers last-used location fields across scans
- Live registration progress with per-step status
- Server list with provisioning status

### Kubernetes Manifests (`k8s/`)

- `onboarding-api.yaml` — Deployment, Service, Ingress, RBAC for the API server
- `kea-dhcp.yaml` — DaemonSet running Kea DHCP4 + Control Agent on ironic-conductor nodes
- `namespace.yaml` — Onboarding namespace

## Development

### API Server

```bash
cd server
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run with auth disabled (no OIDC issuer configured)
uvicorn app.main:app --reload

# Run tests
pytest
```

### PWA

```bash
cd web
npm install
npm run dev     # Dev server with API proxy to localhost:8000
npm run build   # Production build
```

### Docker

```bash
# API server
docker build -t dcaas-onboarding-api server/

# PWA
docker build -t dcaas-onboarding-web web/
```

## Configuration

The API server is configured via environment variables (prefix `ONBOARDING_`):

| Variable | Description |
|----------|-------------|
| `ONBOARDING_OIDC_ISSUER` | OIDC provider URL (empty = auth disabled) |
| `ONBOARDING_OIDC_AUDIENCE` | Expected JWT audience |
| `ONBOARDING_OIDC_REQUIRED_GROUP` | Required group claim |
| `ONBOARDING_NETBOX_URL` | Netbox API URL |
| `ONBOARDING_NETBOX_TOKEN` | Netbox API token |
| `ONBOARDING_OPENBAO_URL` | OpenBao/Vault URL |
| `ONBOARDING_OPENBAO_ROLE_ID` | AppRole role ID |
| `ONBOARDING_OPENBAO_SECRET_ID` | AppRole secret ID |
| `ONBOARDING_OPENBAO_MOUNT_POINT` | KV v2 mount point (default: `secret`) |
| `ONBOARDING_KEA_SERVERS` | JSON list of Kea CA host IPs |
| `ONBOARDING_KEA_PORT` | Kea Control Agent port (default: 8000) |
| `ONBOARDING_KEA_SUBNET_ID` | Kea subnet ID for reservations |
| `ONBOARDING_BMC_PREFIX` | Netbox IPAM prefix for BMC IPs |
| `ONBOARDING_METAL3_NAMESPACE` | K8s namespace for Metal3 resources |

## Naming Convention

Device names are auto-generated: `{site}-{rack}u{position}` (e.g., `dcoa-rb06u31`).

## JSON Import

Servers can be bulk-imported via `POST /api/v1/servers/import` (or streamed via WebSocket at `/api/v1/servers/import/ws`). The endpoint accepts a JSON array of server objects.

### JSON Format

```json
[
  {
    "device_name": "dcoa-ra07u45",
    "bmc_mac": "3CECEFA19CE8",
    "bmc_password": "secret123",
    "bmc_ip": "10.16.28.78",
    "site": "dcoa",
    "location": "ra07",
    "rack": "RA07",
    "position": 45,
    "device_type": "supermicro-1u",
    "device_role": "k8s-worker",
    "bmc_prefix": "10.16.28.0/24",
    "tenant": ""
  }
]
```

**Required fields:**

| Field | Description |
|-------|-------------|
| `device_name` | Server name (e.g., `dcoa-ra07u45`) |
| `bmc_mac` | BMC MAC address — hex (`3CECEFA19CE8`), colon-separated, or hyphen-separated |
| `bmc_password` | BMC login password |

**Optional fields (Netbox integration):**

| Field | Description |
|-------|-------------|
| `site` | Netbox site slug |
| `location` | Netbox location slug |
| `rack` | Rack name |
| `position` | Rack U position (integer) |
| `device_type` | Netbox device type slug |
| `device_role` | Netbox device role slug |
| `bmc_prefix` | IPAM prefix for BMC IP allocation (e.g., `10.16.28.0/24`) |
| `tenant` | Netbox tenant slug |
| `bmc_ip` | Pre-assigned BMC IP (skips Netbox IPAM allocation) |

### Workflow Steps

Each server is processed independently — one failure does not stop others.

1. **Netbox** (conditional) — Creates device + BMC interface, allocates IP from IPAM. Runs only if all Netbox fields (`site`, `location`, `rack`, `position`, `device_type`, `device_role`) are provided; otherwise skipped with a warning.
2. **OpenBao** (always) — Stores BMC credentials at `secret/data/bmc/{device_name}`.
3. **Kea DHCP** (conditional) — Creates DHCP reservation with hostname `{device_name}-bmc`. Runs only if a `bmc_ip` is available (explicitly provided or allocated from Netbox).
4. **Metal3** (conditional) — Creates `BareMetalHost` CRD + BMC Secret. Runs only if a `bmc_ip` is available.

All steps are idempotent — safe to re-import the same servers.

### Minimal Import Example

If you only have MAC, password, and IP (no Netbox):

```json
[
  {
    "device_name": "dcoa-ra07u45",
    "bmc_mac": "3CECEFA19CE8",
    "bmc_password": "secret123",
    "bmc_ip": "10.16.28.78"
  }
]
```

### Merge Script

`scripts/merge-import.py` merges a YAML device list with Kea's JSON reservation file to produce import JSON:

```bash
./scripts/merge-import.py servers.yaml bmc-reservations.json > import.json
```

The YAML file lists device names and passwords:
```yaml
- device_name: ra07u01
  bmc_password: secret123
```

The Kea JSON file provides MAC and IP data. The script matches by hostname and outputs a merged JSON array ready for import.

## Kea DHCP Migration (TODO)

The Kubernetes Kea deployment (`k8s/kea-dhcp.yaml`) currently handles BMC/IPMI DHCP reservations only. To fully replace the existing DHCP server on `internal-dco-test-kvmhost-1.platform.sunet.se`, the following gaps need to be addressed:

### Current K8s Kea Config

- Single subnet: `10.16.28.0/24` (IPMI/BMC), reservation-only (no pools)
- Single interface: `bond0.4002`
- PostgreSQL backend with `libdhcp_host_cmds.so` for API-driven reservations
- HTTP control socket on port 8000

### What the KVM Host Kea Has (that K8s Kea Lacks)

**PXE Boot Subnet** — Second subnet `172.16.0.0/22` on a separate interface (`eno3` on the KVM host), with:
- Pool: `172.16.0.11 - 172.16.3.200`
- `next-server: 172.16.0.10`
- Client classes for UEFI PXE (`netboot.xyz.efi`), BIOS PXE (`netboot.xyz.kpxe`), and UEFI HTTP boot
- NTP server option: `10.16.28.10`

**DHCP Pools** — Both subnets have dynamic pools:
- IPMI: `10.16.28.11 - 10.16.28.200`
- PXE: `172.16.0.11 - 172.16.3.200`

**DHCP Options** — Missing from K8s config:
- DNS servers: `89.32.32.32, 8.8.8.8`
- Domain search: `platform.sunet.se, sunet.se`
- Router/gateway per subnet (`10.16.28.1` and `172.16.0.1`)

**Existing Reservations** — The KVM host uses JSON include files (`bmc-reservations.json`, `pxe-reservations.json`) that need to be migrated into the PostgreSQL database.

### Migration Steps

1. **Network plumbing** — Ensure K8s nodes running Kea have access to both VLANs (IPMI and PXE). Identify the PXE VLAN interface name on K8s nodes (equivalent of `eno3`).
2. **Update Kea config** — Add PXE subnet, pools, DHCP options, client classes, and second interface.
3. **Migrate reservations** — Import existing reservations from JSON files into PostgreSQL (via Kea control API or direct DB inserts).
4. **Switch IP helpers** — Configure switches to point DHCP relay (`ip helper-address`) to K8s node IPs instead of KVM host IP. This is the cutover moment.
5. **Test** — Verify DHCP and PXE boot work from K8s Kea before decommissioning KVM host DHCP.

## License

GNU Affero General Public License v3 — see [LICENSE](LICENSE).
