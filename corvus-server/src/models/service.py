"""Service type definitions for Corvus CMDB."""

from enum import StrEnum


class ServiceType(StrEnum):
    """Service types for failure mode analysis and triage."""

    # Infrastructure
    CONTAINER = "container"
    HOST = "host"
    NETWORK = "network"
    VOLUME = "volume"
    IMAGE = "image"

    # Databases
    POSTGRES = "postgres"
    MYSQL = "mysql"
    MONGODB = "mongodb"
    REDIS = "redis"
    NEO4J = "neo4j"
    MILVUS = "milvus"

    # AI/ML
    INFERENCE = "inference"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    VECTOR_DB = "vector_db"

    # Web Services
    WEB_SERVER = "web_server"
    API_GATEWAY = "api_gateway"
    REVERSE_PROXY = "reverse_proxy"
    LOAD_BALANCER = "load_balancer"

    # Message Brokers
    KAFKA = "kafka"
    RABBITMQ = "rabbitmq"
    MQTT = "mqtt"

    # Monitoring
    PROMETHEUS = "prometheus"
    GRAFANA = "grafana"
    NETDATA = "netdata"
    SPLUNK = "splunk"

    # AI Agents
    AI_AGENT = "ai_agent"
    AI_SUPERVISOR = "ai_supervisor"
    MCP_SERVER = "mcp_server"
    LLM_GATEWAY = "llm_gateway"

    # CAIPE-specific (Phase 2 - Corvus-CAIPE Integration)
    CAIPE_AGENT = "caipe-agent"
    CAIPE_SUPERVISOR = "caipe-supervisor"
    CAIPE_UI = "caipe-ui"
    CAIPE_RAG = "caipe-rag"

    # Homelab-specific
    DOCKER_MCP = "docker-mcp"
    HOMEASSISTANT = "homeassistant"
    UNIFI = "unifi"
    POWERDNS = "powerdns"

    # Automation
    PREFECT = "prefect"
    AIRFLOW = "airflow"
    GITHUB_ACTIONS = "github_actions"

    # Security
    KEYCLOAK = "keycloak"
    VAULT = "vault"
    OPENSEARCH = "opensearch"

    # Other
    UNKNOWN = "unknown"


# Service type to category mapping for grouping
SERVICE_CATEGORIES: dict[str, list[ServiceType]] = {
    "infrastructure": [
        ServiceType.CONTAINER,
        ServiceType.HOST,
        ServiceType.NETWORK,
        ServiceType.VOLUME,
        ServiceType.IMAGE,
    ],
    "databases": [
        ServiceType.POSTGRES,
        ServiceType.MYSQL,
        ServiceType.MONGODB,
        ServiceType.REDIS,
        ServiceType.NEO4J,
        ServiceType.MILVUS,
    ],
    "ai_ml": [
        ServiceType.INFERENCE,
        ServiceType.EMBEDDING,
        ServiceType.RERANK,
        ServiceType.VECTOR_DB,
        ServiceType.LLM_GATEWAY,
    ],
    "web_services": [
        ServiceType.WEB_SERVER,
        ServiceType.API_GATEWAY,
        ServiceType.REVERSE_PROXY,
        ServiceType.LOAD_BALANCER,
    ],
    "message_brokers": [
        ServiceType.KAFKA,
        ServiceType.RABBITMQ,
        ServiceType.MQTT,
    ],
    "monitoring": [
        ServiceType.PROMETHEUS,
        ServiceType.GRAFANA,
        ServiceType.NETDATA,
        ServiceType.SPLUNK,
        ServiceType.OPENSEARCH,
    ],
    "ai_agents": [
        ServiceType.AI_AGENT,
        ServiceType.AI_SUPERVISOR,
        ServiceType.MCP_SERVER,
    ],
    "caipe": [
        ServiceType.CAIPE_AGENT,
        ServiceType.CAIPE_SUPERVISOR,
        ServiceType.CAIPE_UI,
        ServiceType.CAIPE_RAG,
    ],
    "homelab": [
        ServiceType.DOCKER_MCP,
        ServiceType.HOMEASSISTANT,
        ServiceType.UNIFI,
        ServiceType.POWERDNS,
    ],
    "automation": [
        ServiceType.PREFECT,
        ServiceType.AIRFLOW,
        ServiceType.GITHUB_ACTIONS,
    ],
    "security": [
        ServiceType.KEYCLOAK,
        ServiceType.VAULT,
    ],
}


def get_service_category(service_type: ServiceType | str) -> str:
    """Get the category for a service type."""
    if isinstance(service_type, str):
        service_type = ServiceType(service_type)

    for category, types in SERVICE_CATEGORIES.items():
        if service_type in types:
            return category
    return "other"


def is_caipe_service(service_type: ServiceType | str) -> bool:
    """Check if a service type is CAIPE-related."""
    return get_service_category(service_type) == "caipe"
