# AI Foundry APIM MCP Server

MCP (Model Context Protocol) server for Azure AI Foundry that exposes project management and chat operations as tools. Uses OAuth bearer token authentication to connect to Azure.

## Features

### Tools

- **connect** – Connect to a project by endpoint URL OR by account_name + project_name (auto-discovers endpoint)
- **list_projects** – Auto-discover all AI Foundry accounts and projects across all your Azure subscriptions
- **list_connections** – List all gateway connections with optional type filtering (ModelGateway, ApiManagement, AzureOpenAI, etc.)
- **list_models** – List model deployments with name, version, publisher, capabilities, SKU, and connection info
- **list_agents** – List existing agents in the project
- **create_agent** – Create or update an agent with a specific model and gateway connection
- **delete_agent** – Delete an agent
- **chat** – Send a message to an agent and get a response
- **direct_chat** – Call Foundry models directly without agent abstraction
- **list_projects** – List AI Foundry projects under an account via ARM API

### Prompts

MCP prompts are pre-configured workflows that guide the LLM through multi-step tasks:

- **setup_and_explore** – Walk through connecting and exploring your Foundry project (connections, models, agents)
- **create_and_test_agent** – Create an agent with a gateway connection and test it with a message
- **compare_gateways** – Compare different gateway connections by creating test agents and evaluating performance

## Quick Start

1. Start the server: `uv run foundry-mcp-server`
2. From your MCP client, discover and connect:
   ```python
   # Option 1: Auto-discover all projects
   projects = list_projects()  # Lists all accounts and projects
   
   # Option 2a: Connect by account + project name
   connect(account_name="my-foundry-account", project_name="my-project")
   
   # Option 2b: Connect by endpoint URL
   connect(endpoint="https://ai-foundry-xxx.services.ai.azure.com/api/projects/my-project")
   ```
3. Then use any tool or prompt:
   - **Tools**: `list_models()`, `list_connections(connection_type="ModelGateway")`, `create_agent(...)`, etc.
   - **Prompts**: Use `setup_and_explore` to get started, or `create_and_test_agent` to create and test an agent

## Authentication

The server supports two auth modes, controlled by the `AUTH_MODE` env var:

| Mode | `AUTH_MODE` | When to use |
|---|---|---|
| **DefaultAzureCredential** | `default_credential` (default) | Local dev — uses Azure CLI, managed identity, VS Code, etc. |
| **Token passthrough** | `passthrough` | Production / remote — bearer token from MCP client is forwarded to Foundry |

**Local development** (default, no extra config needed):
```bash
az login   # sign in once
uv run foundry-mcp-server
```

**Production / remote**:
```bash
AUTH_MODE=passthrough uv run foundry-mcp-server
# MCP client must send Authorization: Bearer <token>
```

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- An Azure AI Foundry project with a connection string
- An OAuth token with access to your AI Foundry project

## Setup

```bash
# Clone and install
git clone <repo-url>
cd foundry-apim-mcp-server
uv sync

# Configure
cp .env.example .env
# Edit .env with your AI Foundry connection string and deployment name
```

### Environment Variables

| Variable | Description | Required |
|---|---|---|
| `AZURE_AI_FOUNDRY_CONNECTION_STRING` | AI Foundry project endpoint | Yes |
| `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME` | Default model deployment (e.g. `gpt-5-mini`) | Yes |
| `AZURE_BEARER_TOKEN` | Bearer token (only when `AUTH_MODE=passthrough`, for dev) | No |
| `AUTH_MODE` | `default_credential` (default) or `passthrough` | No |
| `AZURE_TENANT_ID` | Tenant ID for DefaultAzureCredential | No |
| `MCP_HOST` | Host to bind the server to (default: `127.0.0.1`) | No |
| `MCP_PORT` | Port to run the server on (default: `8000`) | No |

## Running

```bash
# Run with streamable HTTP transport (default)
uv run foundry-mcp-server

# Or run directly
uv run python -m foundry_apim_mcp_server.server
```

The server starts on `http://localhost:8000/mcp` by default.

## Authentication

The server expects an OAuth bearer token in requests. The token should be an Azure Entra ID access token with permissions to the AI Foundry project.

**For development**, set `AZURE_BEARER_TOKEN` in your `.env` file:

```bash
# Get a token via Azure CLI
az account get-access-token --resource https://cognitiveservices.azure.com --query accessToken -o tsv
```

**For production**, configure your MCP client with OAuth pointing to your Entra ID tenant.

## MCP Client Configuration

### Claude Desktop / Copilot

```json
{
  "mcpServers": {
    "ai-foundry": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer <your-token>"
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
# Install in dev mode
uv sync

# Run with auto-reload
uv run fastmcp dev foundry_apim_mcp_server/server.py
```
