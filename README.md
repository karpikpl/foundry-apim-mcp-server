# AI Foundry APIM MCP Server

MCP (Model Context Protocol) server for Azure AI Foundry that exposes project management, model deployments, agents, and chat operations as tools. Supports both local development (Azure CLI auth) and production (OAuth token passthrough).

## Quick Start

```bash
# Install
git clone <repo-url>
cd foundry-apim-mcp-server
uv sync

# Login to Azure (default auth mode)
az login

# Start the server
uv run foundry-mcp-server
```

The server starts on `http://localhost:8000/mcp` (streamable HTTP transport).

From your MCP client:

```
1. list_projects()                          # discover available projects
2. connect(account_name="...", project_name="...")  # connect to one
3. list_models()                            # see deployed models
4. create_agent(name="my-agent", ...)       # create an agent
5. chat(agent_name="my-agent", message="Hello!")    # chat with it
```

## Project Tag Filter

> **Important:** By default, `list_projects` only returns projects that have a **`TechConnect`** tag in Azure.
> Projects without this tag are silently skipped.
>
> To change or disable this filter, edit `PROJECT_TAG_FILTER` in
> `foundry_apim_mcp_server/foundry_client.py`:
>
> ```python
> PROJECT_TAG_FILTER = "TechConnect"  # set to None to disable filtering
> ```

## Tools

| Tool | Description |
|---|---|
| `list_projects` | Discover all AI Foundry accounts and projects across your Azure subscriptions (no connection required) |
| `connect` | Connect to a project by account_name + project_name (recommended) or by direct endpoint URL |
| `list_connections` | List gateway connections, with optional type filter (`ModelGateway`, `ApiManagement`, `AzureOpenAI`, `AzureAISearch`, `AzureBlob`, `CosmosDB`, `GroundingWithBingSearch`) |
| `list_models` | List model deployments with optional publisher/name filters |
| `list_agents` | List agents in the connected project |
| `create_agent` | Create or update an agent with a model, gateway connection, and optional MCP tools |
| `delete_agent` | Delete an agent by name |
| `chat` | Send a message to an agent and get a response (with MCP tool approval handling) |
| `direct_chat` | Call a model directly without the agent abstraction |

## Prompts

Pre-configured workflows that guide the LLM through multi-step tasks:

| Prompt | Description |
|---|---|
| `setup_and_explore` | Connect to a project and explore connections, models, and agents |
| `create_and_test_agent` | Create an agent with a gateway connection and test it |
| `compare_gateways` | Compare different gateway connections by creating test agents |

## Authentication

Controlled by the `AUTH_MODE` environment variable:

| Mode | `AUTH_MODE` value | How it works |
|---|---|---|
| **DefaultAzureCredential** (default) | `default_credential` | Uses Azure CLI, managed identity, VS Code credential, etc. |
| **Token passthrough** | `passthrough` | Forwards the OAuth bearer token from the MCP client to Foundry |

**Local development** — just sign in once, no other config needed:

```bash
az login
uv run foundry-mcp-server
```

**Production / remote** — the MCP client must send an Azure Entra ID bearer token:

```bash
AUTH_MODE=passthrough uv run foundry-mcp-server
```

## Environment Variables

All variables are optional. Copy `.env.example` to `.env` to get started:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|---|---|---|
| `AZURE_AI_FOUNDRY_CONNECTION_STRING` | AI Foundry project endpoint. Not needed if you use `connect` at runtime. | — |
| `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME` | Default model deployment for `create_agent` / `direct_chat` (e.g. `gpt-5-mini`) | — |
| `AUTH_MODE` | `default_credential` or `passthrough` | `default_credential` |
| `AZURE_TENANT_ID` | Tenant ID hint for DefaultAzureCredential | — |
| `AZURE_BEARER_TOKEN` | Manual bearer token (only for `passthrough` mode during dev) | — |
| `MCP_HOST` | Host to bind the server to | `127.0.0.1` |
| `MCP_PORT` | Port to run the server on | `8000` |

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Azure CLI (`az login`) for default auth mode
- An Azure AI Foundry project

## MCP Client Configuration

### VS Code / Claude Desktop

```json
{
  "mcpServers": {
    "ai-foundry": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

When using `AUTH_MODE=passthrough`, add the Authorization header:

```json
{
  "mcpServers": {
    "ai-foundry": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer <your-entra-id-token>"
      }
    }
  }
}
```

### AI Foundry Agent (as MCP tool)

```python
from azure.ai.projects.models import MCPTool

mcp_tool = MCPTool(
    server_label="ai-foundry-mcp",
    server_url="http://localhost:8000/mcp",
    require_approval="never",
)
```

## Docker

```bash
# Build
docker build -t foundry-mcp-server .

# Run with managed identity (e.g. on Azure Container Apps / ACI)
docker run -p 8000:8000 foundry-mcp-server

# Run with token passthrough
docker run -p 8000:8000 -e AUTH_MODE=passthrough foundry-mcp-server

# Run with an .env file
docker run -p 8000:8000 --env-file .env foundry-mcp-server
```

> The image defaults to `MCP_HOST=0.0.0.0` so it listens on all interfaces inside the container.

## Authentication Flow

This server does **not** use OBO (On-Behalf-Of) flow.

It supports two modes, controlled by the `AUTH_MODE` environment variable:

| Mode | `AUTH_MODE` | How it works |
|---|---|---|
| **DefaultAzureCredential** (default) | `default_credential` | Uses the standard Azure Identity chain: managed identity → Azure CLI → environment variables → VS Code credential. In production containers this typically resolves to **managed identity**. |
| **Token passthrough** | `passthrough` | The MCP client sends an Azure Entra ID bearer token in the `Authorization` header; the server forwards that same token to Azure AI Foundry APIs. No token exchange or OBO is involved. |

### Required Azure RBAC Permissions

The identity (managed identity or user principal) must have:

| Permission / Role | Scope | Why |
|---|---|---|
| **Reader** | Subscription(s) or Management Group | `list_projects` makes ARM management plane calls to enumerate subscriptions, Cognitive Services accounts, and projects (see actions below) |
| **Cognitive Services OpenAI User** | AI Foundry project resource | Required to call model deployments, create/manage agents, and chat |
| **Cognitive Services Contributor** *(optional)* | AI Foundry project resource | Only needed if you want to create or delete agents via the server |

> If you only `connect` to a known project endpoint (skip `list_projects`), the **Reader** role on the subscription is not required.

<details>
<summary>Specific ARM actions required by <code>list_projects</code></summary>

If using a custom role instead of the built-in **Reader**, grant these actions:

| ARM Action | Used for |
|---|---|
| `Microsoft.Resources/subscriptions/read` | Enumerate accessible subscriptions |
| `Microsoft.CognitiveServices/accounts/read` | List AI Foundry / Cognitive Services accounts per subscription |
| `Microsoft.CognitiveServices/accounts/projects/read` | List projects under each account |

</details>

## Environment Variables Reference

| Variable | Required | Description | Default |
|---|---|---|---|
| `AUTH_MODE` | No | `default_credential` or `passthrough` | `default_credential` |
| `AZURE_AI_FOUNDRY_CONNECTION_STRING` | No | AI Foundry project endpoint. Not needed if you call `connect` at runtime. | — |
| `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME` | No | Default model deployment for `create_agent` / `direct_chat` (e.g. `gpt-5-mini`) | — |
| `AZURE_TENANT_ID` | No | Tenant ID hint for DefaultAzureCredential | — |
| `AZURE_BEARER_TOKEN` | No | Manual bearer token (only for `passthrough` mode during dev) | — |
| `AZURE_CLIENT_ID` | No | Client ID for managed identity (set when using user-assigned managed identity) | — |
| `MCP_HOST` | No | Host to bind the server to | `127.0.0.1` (`0.0.0.0` in Docker) |
| `MCP_PORT` | No | Port to run the server on | `8000` |

## Development

```bash
uv sync

# Run with auto-reload (FastMCP dev mode)
uv run fastmcp dev foundry_apim_mcp_server/server.py

# Or run directly
uv run python -m foundry_apim_mcp_server.server
```
