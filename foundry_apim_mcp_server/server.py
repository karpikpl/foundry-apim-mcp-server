"""AI Foundry MCP Server - exposes Azure AI Foundry operations as MCP tools."""

import logging
import os
from enum import Enum

from dotenv import load_dotenv
from fastmcp import FastMCP, Context
from pydantic import Field

from .auth import BearerTokenCredential
from .foundry_client import FoundryClient

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Session state: endpoint set via `connect` tool (or env var fallback)
_session_endpoint: str | None = None
_session_credential = None  # Cache credential to avoid recreating it


class ConnectionType(str, Enum):
    """Azure AI Foundry connection types."""

    ALL = "all"
    MODEL_GATEWAY = "ModelGateway"
    API_MANAGEMENT = "ApiManagement"
    AZURE_OPEN_AI = "AzureOpenAI"
    AZURE_AI_SEARCH = "AzureAISearch"
    AZURE_BLOB = "AzureBlob"
    COSMOS_DB = "CosmosDB"
    GROUNDING_BING = "GroundingWithBingSearch"


def _use_default_credential() -> bool:
    """Check if we should use DefaultAzureCredential instead of token passthrough.

    Set AUTH_MODE=default_credential (or leave unset when running locally)
    to use DefaultAzureCredential (Azure CLI, managed identity, etc.).
    Set AUTH_MODE=passthrough to require an OAuth bearer token from the MCP client.
    """
    mode = os.environ.get("AUTH_MODE", "default_credential").lower()
    return mode != "passthrough"


def _get_credential():
    """Get the appropriate Azure credential based on AUTH_MODE.

    Reuses the same credential instance to avoid unclosed session warnings.
    """
    global _session_credential

    # In default_credential mode, reuse the same credential
    if _use_default_credential():
        if _session_credential is None:
            from azure.identity.aio import DefaultAzureCredential

            tenant_id = os.environ.get("AZURE_TENANT_ID")
            kwargs = {"tenant_id": tenant_id} if tenant_id else {}
            _session_credential = DefaultAzureCredential(**kwargs)
        return _session_credential

    # Passthrough mode: always create new BearerTokenCredential (it's lightweight)
    try:
        from fastmcp.server.dependencies import get_access_token

        token = get_access_token()
        if token and hasattr(token, "token"):
            return BearerTokenCredential(token.token)
    except Exception:
        pass

    token = os.environ.get("AZURE_BEARER_TOKEN", "")
    if token:
        return BearerTokenCredential(token)

    raise ValueError(
        "No bearer token found. Pass a token via OAuth, set AZURE_BEARER_TOKEN, "
        "or set AUTH_MODE=default_credential to use DefaultAzureCredential."
    )


def _get_endpoint() -> str:
    """Get the active Foundry endpoint from session state or env var."""
    endpoint = _session_endpoint or os.environ.get(
        "AZURE_AI_FOUNDRY_CONNECTION_STRING", ""
    )
    if not endpoint:
        raise ValueError(
            "Not connected. Call the 'connect' tool first with your AI Foundry endpoint, "
            "or set AZURE_AI_FOUNDRY_CONNECTION_STRING."
        )
    return endpoint


def _create_foundry_client() -> FoundryClient:
    """Create a FoundryClient with the appropriate credential and endpoint."""
    credential = _get_credential()
    return FoundryClient(credential=credential, endpoint=_get_endpoint())


# ── MCP Server ───────────────────────────────────────────────────

mcp = FastMCP(
    name="AI Foundry MCP Server",
    instructions=(
        "MCP server for Azure AI Foundry. Start by calling the 'connect' tool with your "
        "AI Foundry project endpoint, then use the other tools to manage connections, "
        "models, agents, and chat. Requires an OAuth bearer token for Azure authentication."
    ),
)


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from starlette.responses import JSONResponse

    return JSONResponse({"status": "ok"})


# ── Tools ────────────────────────────────────────────────────────


@mcp.tool
async def connect(
    ctx: Context,
    endpoint: str | None = Field(
        default=None,
        description=(
            "OPTIONAL: Direct endpoint URL like "
            "'https://ai-foundry-xxx.services.ai.azure.com/api/projects/my-project'. "
            "Only needed if you're not using account_name + project_name."
        ),
    ),
    account_name: str | None = Field(
        default=None,
        description=(
            "RECOMMENDED: Account name from list_projects. "
            "Use with project_name to auto-discover endpoint."
        ),
    ),
    project_name: str | None = Field(
        default=None,
        description=(
            "RECOMMENDED: Project name from list_projects. "
            "Use with account_name to auto-discover endpoint."
        ),
    ),
) -> dict:
    """Connect to an AI Foundry project.

    **Two ways to connect (choose one):**

    **Method 1 (Recommended):** Use account_name + project_name
    - Call list_projects() first to see available projects
    - Then: connect(account_name="my-account", project_name="my-project")
    - The endpoint will be discovered automatically

    **Method 2:** Use direct endpoint URL
    - connect(endpoint="https://ai-foundry-xxx.../api/projects/my-project")
    - Use this if you already know the full endpoint URL

    **Examples:**
    - connect(account_name="my-foundry", project_name="prod")
    - connect(endpoint="https://ai-foundry-123.services.ai.azure.com/api/projects/p1")

    Sets the project endpoint for this session. All subsequent tool calls
    will use this endpoint. Validates the connection by listing available connections.
    """
    global _session_endpoint

    # Determine the endpoint
    if endpoint:
        # Direct connection with endpoint URL
        if account_name or project_name:
            raise ValueError(
                "Provide either 'endpoint' OR 'account_name'+'project_name', not both."
            )
        _session_endpoint = endpoint
    elif account_name and project_name:
        # Auto-discover endpoint from account + project
        _session_endpoint = f"https://{account_name}.services.ai.azure.com/api/projects/{project_name}"
    else:
        raise ValueError(
            "Provide either 'endpoint' OR both 'account_name' and 'project_name'."
        )

    # Validate by attempting to list connections
    client = _create_foundry_client()
    try:
        connections = await client.list_connections()
        return {
            "connected": True,
            "endpoint": _session_endpoint,
            "account_name": account_name,
            "project_name": project_name,
            "connections_found": len(connections),
            "connection_names": [c.name for c in connections],
        }
    except Exception as e:
        _session_endpoint = None
        raise ValueError(f"Failed to connect to {_session_endpoint}: {e}") from e
    finally:
        await client.close()


@mcp.tool
async def list_connections(
    ctx: Context,
    connection_type: ConnectionType = Field(
        default=ConnectionType.ALL,
        description="Filter by connection type (e.g. 'ModelGateway', 'ApiManagement', 'AzureOpenAI')",
    ),
) -> list[dict]:
    """List all gateway connections in the AI Foundry project.

    Returns connections with their name, type (ModelGateway, ApiManagement, AzureOpenAI, etc.),
    target URL, whether they are the default, and metadata.

    Filter by connection_type to see only specific types of connections.
    """
    client = _create_foundry_client()
    try:
        connections = await client.list_connections()
        # Filter by type if not "all"
        if connection_type != ConnectionType.ALL:
            connections = [c for c in connections if c.type == connection_type.value]
        return [
            {
                "id": c.id,
                "name": c.name,
                "type": c.type,
                "is_default": c.is_default,
                "target": c.target,
                "metadata": c.metadata,
            }
            for c in connections
        ]
    finally:
        await client.close()


@mcp.tool
async def list_models(
    ctx: Context,
    model_publisher: str | None = Field(
        default=None,
        description="Filter by model publisher (e.g. 'OpenAI', 'Microsoft')",
    ),
    model_name: str | None = Field(
        default=None,
        description="Filter by model name (e.g. 'gpt-5-mini')",
    ),
) -> list[dict]:
    """List model deployments available in the AI Foundry project.

    Returns deployment name, model name/version/publisher, capabilities,
    SKU info, and which connection the deployment belongs to.
    """
    client = _create_foundry_client()
    try:
        deployments = await client.list_deployments(
            model_publisher=model_publisher,
            model_name=model_name,
        )
        return [
            {
                "name": d.name,
                "model_name": d.model_name,
                "model_version": d.model_version,
                "model_publisher": d.model_publisher,
                "capabilities": d.capabilities,
                "sku_name": d.sku_name,
                "sku_capacity": d.sku_capacity,
                "connection_name": d.connection_name,
            }
            for d in deployments
        ]
    finally:
        await client.close()


@mcp.tool
async def list_agents(ctx: Context) -> list[dict]:
    """List all agents in the AI Foundry project.

    Returns agent name, ID, version, and model deployment.
    """
    client = _create_foundry_client()
    try:
        agents = await client.list_agents()
        return agents
    finally:
        await client.close()


@mcp.tool
async def create_agent(
    ctx: Context,
    name: str = Field(description="Name for the agent"),
    instructions: str = Field(
        default="You are a helpful assistant that answers general questions",
        description="System instructions for the agent",
    ),
    model_gateway_connection: str | None = Field(
        default=None,
        description="Gateway connection name to route through (e.g. 'my-apim-connection'). If not provided, uses direct model deployment.",
    ),
    deployment_name: str | None = Field(
        default=None,
        description="Model deployment name (e.g. 'gpt-5-mini'). Defaults to AZURE_OPENAI_CHAT_DEPLOYMENT_NAME env var.",
    ),
    delete_before_create: bool = Field(
        default=True,
        description="Delete existing agent with same name before creating",
    ),
    mcp_tools: list[str] = Field(
        default=[],
        description="List of MCP tools to include in the agent. Names should match mcp tool names from connections",
    ),
) -> dict:
    """Create or update an agent in AI Foundry.

    Creates a new agent with the specified model and gateway connection.
    If an agent with the same name exists, it will be deleted first (unless delete_before_create=False).
    """
    client = _create_foundry_client()
    try:
        agent = await client.create_agent(
            name=name,
            model_gateway_connection=model_gateway_connection,
            instructions=instructions,
            deployment_name=deployment_name,
            delete_before_create=delete_before_create,
            tools=mcp_tools,
        )
        return {
            "id": agent.id,
            "name": agent.name,
            "version": agent.version,
            "model": agent.model,
        }
    finally:
        await client.close()


@mcp.tool
async def delete_agent(
    ctx: Context,
    name: str = Field(description="Name of the agent to delete"),
) -> dict:
    """Delete an agent from the AI Foundry project."""
    client = _create_foundry_client()
    try:
        await client.delete_agent(name=name)
        return {"deleted": True, "name": name}
    finally:
        await client.close()


@mcp.tool
async def chat(
    ctx: Context,
    agent_name: str = Field(description="Name of the agent to chat with"),
    message: str = Field(description="User message to send"),
) -> dict:
    """Send a message to an AI Foundry agent and get a response.

    Creates a conversation, sends the message to the specified agent,
    and returns the agent's response along with usage statistics.
    """
    client = _create_foundry_client()
    try:
        return await client.chat(agent_name=agent_name, message=message)
    finally:
        await client.close()


@mcp.tool
async def direct_chat(
    ctx: Context,
    message: str = Field(description="User message to send"),
    model_connection: str | None = Field(
        default=None,
        description="Gateway connection name to route through",
    ),
    deployment_name: str | None = Field(
        default=None,
        description="Model deployment name. Defaults to AZURE_OPENAI_CHAT_DEPLOYMENT_NAME env var.",
    ),
    instructions: str = Field(
        default="You are a helpful assistant.",
        description="System instructions for the model",
    ),
) -> dict:
    """Call AI Foundry directly without agent abstraction.

    Sends a message directly to a model deployment, optionally routed
    through a gateway connection. Useful for quick one-off queries.
    """
    client = _create_foundry_client()
    try:
        return await client.direct_chat(
            message=message,
            model_connection=model_connection,
            deployment_name=deployment_name,
            instructions=instructions,
        )
    finally:
        await client.close()


@mcp.tool
async def list_projects(ctx: Context) -> list[dict]:
    """List all AI Foundry accounts and projects across all your Azure subscriptions.

    Automatically discovers:
    - All subscriptions you have access to
    - All AI Foundry accounts in those subscriptions
    - All projects under each account

    Returns account name, project name, location, and endpoint for each project.
    Use this to discover what's available before calling 'connect'.

    NOTE: This tool does NOT require a prior connection - call it first to discover projects.
    """
    # Get credential without requiring an endpoint (unlike other tools)
    credential = _get_credential()
    # Create client without endpoint validation - we only need credential for ARM API
    client = FoundryClient(
        credential=credential, endpoint=None, skip_endpoint_validation=True
    )
    try:
        return await client.list_all_projects()
    finally:
        await client.close()


# ── Prompts ──────────────────────────────────────────────────────


@mcp.prompt
def setup_and_explore() -> str:
    """Guide for connecting to AI Foundry and exploring available resources.

    Walks through discovering projects, connecting, and exploring connections,
    models, and agents.
    """
    return """# AI Foundry Setup and Exploration

This prompt guides you through discovering and connecting to an AI Foundry project, then exploring its resources.

## Step 1: Discover Available Projects

Call `list_projects` (no parameters needed!) to see all AI Foundry accounts and projects:
- It scans all your Azure subscriptions automatically
- Shows account names, project names, locations, and endpoints
- Note down the account_name and project_name you want to use

## Step 2: Connect to Your Project

Call `connect` using one of two methods:

**Method A: By account and project name (recommended)**
```
connect(account_name="your-account", project_name="your-project")
```

**Method B: By endpoint URL**
```
connect(endpoint="https://ai-foundry-xxx.services.ai.azure.com/api/projects/your-project")
```

The tool will validate the connection and show available connections.

## Step 3: Explore Connections

Call `list_connections` with different connection types to see what's available:
- `connection_type="ModelGateway"` - Gateway connections for model routing
- `connection_type="ApiManagement"` - APIM gateway connections  
- `connection_type="AzureOpenAI"` - Direct Azure OpenAI connections
- `connection_type="all"` - All connection types

Pay attention to:
- Connection names (you'll need these for agents)
- Target URLs
- Default connections

## Step 4: List Available Models

Call `list_models` to see model deployments:
- Optional: filter by `model_publisher` (e.g., "OpenAI")
- Optional: filter by `model_name` (e.g., "gpt-5-mini")
- Note the deployment names and associated connections

## Step 5: List Existing Agents

Call `list_agents` to see what agents are already deployed.

## Summary

Present a summary showing:
- Connected project (account + project name)
- Total connections by type
- Available model deployments
- Existing agents
- Recommended next steps
"""


@mcp.prompt
def create_and_test_agent(
    agent_name: str = "TestAgent",
    connection_name: str = "",
    deployment_name: str = "gpt-5-mini",
    test_message: str = "What is 2+2? Reply with just the number.",
) -> str:
    """Create an agent with a gateway connection and test it with a message.

    This workflow creates an agent routed through a specified gateway connection
    and tests it with a simple query.

    Args:
        agent_name: Name for the new agent
        connection_name: Gateway connection name (from list_connections)
        deployment_name: Model deployment name (e.g., 'gpt-5-mini')
        test_message: Message to test the agent with
    """
    return f"""# Create and Test AI Foundry Agent

This prompt guides you through creating an agent with a gateway connection and testing it.

## Prerequisites

If you haven't already:
1. Call `connect` with your AI Foundry endpoint
2. Call `list_connections(connection_type="ModelGateway")` or `list_connections(connection_type="ApiManagement")` to find gateway connections

## Step 1: Create the Agent

Call `create_agent` with:
- `name`: "{agent_name}"
- `model_gateway_connection`: "{connection_name or '<connection-name-from-list>'}"
- `deployment_name`: "{deployment_name}"
- `instructions`: "You are a helpful assistant."
- `delete_before_create`: true (to replace if it exists)

The tool will return the agent details including ID, version, and full model path.

## Step 2: Test the Agent

Call `chat` with:
- `agent_name`: "{agent_name}"
- `message`: "{test_message}"

This will send a test message to the agent through the configured gateway.

## Step 3: Analyze Results

Check the response for:
- `output`: The agent's response
- `usage`: Token usage statistics
- `request_id`: For debugging/tracking

## Step 4: Verify Gateway Routing

The agent should be using the gateway connection "{connection_name or '<gateway-connection>'}".
Verify by checking:
- The model path in the agent details should be: `{{connection_name}}/{{deployment_name}}`
- The response should come through the gateway (check request_id in gateway logs if available)

## Optional: Direct Comparison

For comparison, you can call `direct_chat` with the same message but WITHOUT the gateway:
- `message`: "{test_message}"
- `deployment_name`: "{deployment_name}"
- `model_connection`: null (or omit)

Compare:
- Response times
- Token usage
- Response quality

## Summary

Present:
- Agent creation status
- Test message and response
- Token usage
- Whether gateway routing is working correctly
"""


@mcp.prompt
def compare_gateways() -> str:
    """Compare different gateway connections by creating agents with each and testing them.

    This workflow helps you evaluate different gateway connections (APIM, Model Gateway, etc.)
    by creating test agents and comparing their performance.
    """
    return """# Compare Gateway Connections

This prompt guides you through comparing different gateway connections in your AI Foundry project.

## Step 1: List All Gateways

Call `list_connections` with:
- `connection_type="ModelGateway"` - Get Model Gateway connections
- `connection_type="ApiManagement"` - Get APIM connections

Make a note of:
- Connection names
- Target URLs
- Which are marked as default

## Step 2: Select Test Configuration

Choose:
- A model deployment to use (from `list_models`)
- A test message (e.g., "What is the capital of France?")
- Gateway connections to compare (at least 2)

## Step 3: Create Test Agents

For each gateway connection:
1. Call `create_agent`:
   - `name`: "TestAgent_{{gateway_name}}" (unique name per gateway)
   - `model_gateway_connection`: "{{gateway_name}}"
   - `deployment_name`: "{{your_chosen_deployment}}"
   - `delete_before_create`: true

2. Verify the agent was created with the correct gateway

## Step 4: Run Comparison Tests

For each test agent:
1. Call `chat`:
   - `agent_name`: "TestAgent_{{gateway_name}}"
   - `message`: "{{your_test_message}}"

2. Record:
   - Response time (if available)
   - Token usage (prompt_tokens, completion_tokens, total_tokens)
   - Response quality
   - Request ID

## Step 5: Compare Results

Create a comparison table showing:

| Gateway | Response Time | Prompt Tokens | Completion Tokens | Total Tokens | Response Quality |
|---------|--------------|---------------|-------------------|--------------|------------------|
| ...     | ...          | ...           | ...               | ...          | ...              |

## Step 6: Cleanup (Optional)

Delete test agents using `delete_agent` if they're no longer needed.

## Summary

Recommend:
- Which gateway performed best
- Which gateway to use for production
- Any notable differences in behavior or cost
"""


async def cleanup():
    """Cleanup async resources on shutdown."""
    global _session_credential
    if _session_credential and hasattr(_session_credential, "close"):
        try:
            await _session_credential.close()
            logger.info("Closed session credential")
        except Exception as e:
            logger.warning(f"Error closing credential: {e}")
        _session_credential = None


def main():
    """Run the MCP server."""
    import atexit
    import asyncio

    def sync_cleanup():
        """Sync wrapper for cleanup."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(cleanup())
            else:
                loop.run_until_complete(cleanup())
        except Exception as e:
            logger.warning(f"Cleanup failed: {e}")

    atexit.register(sync_cleanup)

    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8000"))
    mcp.run(transport="streamable-http", host=host, port=port)


if __name__ == "__main__":
    main()
