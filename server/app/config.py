"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # API server
    app_name: str = "DCaaS Onboarding API"
    debug: bool = False

    # OIDC authentication
    oidc_issuer: str = ""
    oidc_audience: str = "onboarding-api"

    # OIDC BFF (authorization-code flow)
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""
    session_secret: str = ""

    # Allowed users (comma-separated list of OIDC 'sub' values)
    allowed_users: str = ""

    # Netbox
    netbox_url: str = ""
    netbox_token: str = ""

    # OpenBao / Vault
    openbao_url: str = ""
    openbao_role_id: str = ""
    openbao_secret_id: str = ""
    openbao_mount_point: str = "secret"

    # Kea DHCP - ironic-conductor node IPs running Kea Control Agent
    kea_servers: list[str] = []
    kea_port: int = 8000
    kea_subnet_id: int = 1

    # Netbox IPAM - prefix to allocate IPMI IPs from
    ipmi_prefix: str = ""

    # Ironic / Metal3
    metal3_namespace: str = "metal3"
    use_metal3_crd: bool = True

    # Reference data cache TTL in seconds
    reference_cache_ttl: int = 300

    model_config = {"env_prefix": "ONBOARDING_"}


settings = Settings()
