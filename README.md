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
2. Stores IPMI credentials in **OpenBao** (Vault-compatible)
3. Allocates IPMI IP from Netbox IPAM and pushes DHCP reservation to **Kea**
4. Creates `BareMetalHost` CRD + BMC Secret in **Metal3**

### PWA (`web/`)

Progressive Web App with barcode scanning for mobile use:

- Two-step barcode scan: BMC MAC address + IPMI password
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
| `ONBOARDING_IPMI_PREFIX` | Netbox IPAM prefix for IPMI IPs |
| `ONBOARDING_METAL3_NAMESPACE` | K8s namespace for Metal3 resources |

## Naming Convention

Device names are auto-generated: `{site}-{rack}u{position}` (e.g., `dcoa-rb06u31`).

## License

GNU Affero General Public License v3 — see [LICENSE](LICENSE).
