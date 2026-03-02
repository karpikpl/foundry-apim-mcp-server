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

## Development

```bash
uv sync

# Run with auto-reload (FastMCP dev mode)
uv run fastmcp dev foundry_apim_mcp_server/server.py

# Or run directly
uv run python -m foundry_apim_mcp_server.server
```
