"""Azure AI Foundry client wrapper."""

import os
import logging
from dataclasses import dataclass, field

import httpx
from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.core.credentials_async import AsyncTokenCredential
from azure.ai.projects.models import (
    MCPTool,
    Tool,
)
from openai.types.responses import (
    Response,
    ResponseReasoningItem,
    ResponseOutputText,
)

from openai.types.responses.response_input_param import (
    McpApprovalResponse,
)

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────
# Filter projects by tag. Set to None to disable filtering.
PROJECT_TAG_FILTER = "TechConnect"  # Only return projects with this tag


@dataclass
class ConnectionInfo:
    id: str
    name: str
    type: str
    is_default: bool
    target: str
    metadata: dict


@dataclass
class DeploymentInfo:
    name: str
    model_name: str
    model_version: str
    model_publisher: str
    capabilities: dict
    sku_name: str
    sku_capacity: int | None
    connection_name: str | None


@dataclass
class AgentInfo:
    id: str
    name: str
    version: str
    model: str
    tools: list[str]


@dataclass
class ProcessedResponse:
    """Result from processing a streaming or non-streaming response."""

    response_id: str | None = None
    full_response: str = ""
    input_list: list[str] = field(default_factory=list)
    events_received: list[str] = field(default_factory=list)
    usage: dict[str, object] = field(default_factory=dict)
    served_by_cluster: str = "unknown"
    openai_processing_ms: str = "unknown"
    request_id: str = "unknown"


class FoundryClient:
    """Wraps Azure AI Foundry operations for use by MCP tools."""

    def __init__(
        self,
        credential: AsyncTokenCredential,
        endpoint: str | None = None,
        skip_endpoint_validation: bool = False,
    ):
        self.endpoint = endpoint or os.environ.get(
            "AZURE_AI_FOUNDRY_CONNECTION_STRING", ""
        )
        if not self.endpoint and not skip_endpoint_validation:
            raise ValueError("AZURE_AI_FOUNDRY_CONNECTION_STRING must be set")
        self.credential = credential
        self._client: AIProjectClient | None = None

    async def _get_client(self) -> AIProjectClient:
        if self._client is None:
            self._client = AIProjectClient(
                endpoint=self.endpoint,
                credential=self.credential,
            )
        return self._client

    async def close(self):
        """Close all async resources."""
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None

        # Close credential if it's DefaultAzureCredential
        if hasattr(self.credential, "close"):
            try:
                await self.credential.close()
            except Exception:
                pass

    # ── Connections ──────────────────────────────────────────────

    async def list_connections(self) -> list[ConnectionInfo]:
        client = await self._get_client()
        connections = []
        async for conn in client.connections.list():
            connections.append(
                ConnectionInfo(
                    id=conn.id,
                    name=conn.name,
                    type=conn.type,
                    is_default=conn.is_default,
                    target=getattr(conn, "target", ""),
                    metadata=dict(getattr(conn, "metadata", {}) or {}),
                )
            )
        return connections

    # ── Deployments / Models ─────────────────────────────────────

    async def list_deployments(
        self,
        model_publisher: str | None = None,
        model_name: str | None = None,
    ) -> list[DeploymentInfo]:
        """List model deployments available in the project."""
        client = await self._get_client()
        deployments = []
        kwargs = {}
        if model_publisher:
            kwargs["model_publisher"] = model_publisher
        if model_name:
            kwargs["model_name"] = model_name

        async for dep in client.deployments.list(**kwargs):
            sku = getattr(dep, "sku", None)
            deployments.append(
                DeploymentInfo(
                    name=dep.name,
                    model_name=getattr(dep, "model_name", ""),
                    model_version=getattr(dep, "model_version", ""),
                    model_publisher=getattr(dep, "model_publisher", ""),
                    capabilities=dict(getattr(dep, "capabilities", {}) or {}),
                    sku_name=getattr(sku, "name", "") if sku else "",
                    sku_capacity=getattr(sku, "capacity", None) if sku else None,
                    connection_name=getattr(dep, "connection_name", None),
                )
            )
        return deployments

    # ── Agents ───────────────────────────────────────────────────

    async def list_agents(self) -> list[AgentInfo]:
        client = await self._get_client()
        agents = []
        async for agent in client.agents.list():
            agents.append(
                AgentInfo(
                    id=agent.id,
                    name=agent.name,
                    version=agent.versions.latest.version,
                    model=agent.versions.latest.definition.model,
                    tools=[
                        f"{tool.type} {getattr(tool, 'server_label', '')}".strip()
                        for tool in agent.versions.latest.definition.tools or []
                    ],
                )
            )
        return agents

    async def create_agent(
        self,
        name: str,
        model_gateway_connection: str | None = None,
        instructions: str = "You are a helpful assistant that answers general questions",
        deployment_name: str | None = None,
        delete_before_create: bool = True,
        tools: list[str] = [],
    ) -> AgentInfo:
        client = await self._get_client()
        deployment_name = deployment_name or os.environ.get(
            "AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", ""
        )
        if not deployment_name:
            raise ValueError(
                "deployment_name must be provided or set AZURE_OPENAI_CHAT_DEPLOYMENT_NAME"
            )

        model = (
            f"{model_gateway_connection}/{deployment_name}"
            if model_gateway_connection
            else deployment_name
        )

        agent_tools: list[Tool] = []

        if tools:
            # get connections to find tool targets
            connections = await self.list_connections()
            for tool_name in tools:
                matching_conns = [c for c in connections if c.name == tool_name]
                if not matching_conns:
                    logger.warning(
                        f"Tool {tool_name} specified but no matching connection found"
                    )
                    continue
                conn = matching_conns[0]
                agent_tools.append(
                    MCPTool(
                        server_label=tool_name,
                        server_url=conn.target,
                        require_approval="never",
                    )
                )

        # Check existing agents
        existing = await self.list_agents()
        existing_names = [a.name for a in existing]

        if name in existing_names and delete_before_create:
            logger.info(f"Deleting existing agent {name} before re-creating")
            await client.agents.delete(agent_name=name)
            existing_names.remove(name)

        if name not in existing_names:
            agent = await client.agents.create(
                name=name,
                definition=PromptAgentDefinition(
                    model=model, instructions=instructions, tools=agent_tools
                ),
            )
            logger.info(f"Agent created: {agent.name} (id={agent.id})")
        else:
            agent = await client.agents.update(
                agent_name=name,
                definition=PromptAgentDefinition(
                    model=model, instructions=instructions, tools=agent_tools
                ),
            )
            logger.info(f"Agent updated: {agent.name} (id={agent.id})")

        return AgentInfo(
            id=agent.id,
            name=agent.name,
            version=agent.versions.latest.version,
            model=agent.versions.latest.definition.model,
            tools=[
                f"{tool.type} {getattr(tool, 'server_label', '')}".strip()
                for tool in agent.versions.latest.definition.tools or []
            ],
        )

    async def delete_agent(self, name: str) -> bool:
        client = await self._get_client()
        try:
            await client.agents.delete(agent_name=name)
            return True
        except Exception as e:
            logger.error(f"Failed to delete agent {name}: {e}")
            raise

    # ── Chat ─────────────────────────────────────────────────────

    async def chat(
        self,
        agent_name: str,
        message: str,
    ) -> ProcessedResponse:
        """Send a message to an agent and return the response."""
        client = await self._get_client()
        openai_client = client.get_openai_client()

        conversation = await openai_client.conversations.create(
            items=[{"type": "message", "role": "user", "content": message}],
        )

        raw_response = await openai_client.responses.with_raw_response.create(
            conversation=conversation.id,
            extra_body={"agent": {"name": agent_name, "type": "agent_reference"}},
            input="",
        )
        response = raw_response.parse()

        result = await self.process_response(
            response
        )  # Process the response to handle MCP approvals and print events

        result.served_by_cluster = (
            raw_response.headers.get("azureml-served-by-cluster", "unknown"),
        )
        result.openai_processing_ms = (
            raw_response.headers.get("openai-processing-ms", "unknown"),
        )
        result.request_id = (raw_response.headers.get("x-request-id", "unknown"),)
        return result

    async def direct_chat(
        self,
        message: str,
        model_connection: str | None = None,
        deployment_name: str | None = None,
        instructions: str = "You are a helpful assistant.",
    ) -> dict:
        """Call Foundry directly without agent abstraction."""
        client = await self._get_client()
        openai_client = client.get_openai_client()

        deployment_name = deployment_name or os.environ.get(
            "AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", ""
        )
        model = (
            f"{model_connection}/{deployment_name}"
            if model_connection
            else deployment_name
        )

        response = await openai_client.responses.create(
            model=model,
            input=message,
            instructions=instructions,
        )

        result = await self.process_response(
            response
        )  # Process the response to handle MCP approvals and print events
        return result

    # ── Projects & Accounts ──────────────────────────────────────

    async def list_all_projects(
        self, api_version: str = "2025-04-01-preview"
    ) -> list[dict]:
        """Discover all AI Foundry accounts and projects across all subscriptions.

        Returns a list of dicts with account and project information.
        """
        token = await self.credential.get_token("https://management.azure.com/.default")
        headers = {"Authorization": f"Bearer {token.token}"}

        async with httpx.AsyncClient(timeout=30.0) as http_client:
            # Step 1: List all subscriptions
            subs_url = (
                "https://management.azure.com/subscriptions?api-version=2022-12-01"
            )
            subs_resp = await http_client.get(subs_url, headers=headers)
            subs_resp.raise_for_status()
            subscriptions = subs_resp.json().get("value", [])

            all_projects = []

            # Step 2: For each subscription, find Cognitive Services accounts
            for sub in subscriptions:
                sub_id = sub.get("subscriptionId")
                sub_name = sub.get("displayName", sub_id)

                logger.info(f"Scanning subscription: {sub_name}")

                # List all Cognitive Services accounts in this subscription
                accounts_url = (
                    f"https://management.azure.com/subscriptions/{sub_id}"
                    f"/providers/Microsoft.CognitiveServices/accounts"
                    f"?api-version=2023-05-01"
                )

                try:
                    accounts_resp = await http_client.get(accounts_url, headers=headers)
                    accounts_resp.raise_for_status()
                    accounts = accounts_resp.json().get("value", [])

                    # Step 3: For each account, list projects
                    for account in accounts:
                        account_name = account.get("name")
                        account_location = account.get("location")
                        account_kind = account.get("kind", "")
                        account_tags = account.get("tags", {})
                        account_hidden_title = account_tags.get("hidden-title", "")
                        resource_group = (
                            account.get("id", "")
                            .split("/resourceGroups/")[1]
                            .split("/")[0]
                            if "/resourceGroups/" in account.get("id", "")
                            else ""
                        )

                        # Only check AI Foundry / AIServices accounts
                        if account_kind not in ["AIServices", "OpenAI"]:
                            continue

                        logger.info(f"  Found account: {account_name} ({account_kind})")

                        # List projects for this account
                        projects_url = (
                            f"https://management.azure.com/subscriptions/{sub_id}"
                            f"/resourceGroups/{resource_group}"
                            f"/providers/Microsoft.CognitiveServices/accounts/{account_name}"
                            f"/projects?api-version={api_version}"
                        )

                        try:
                            projects_resp = await http_client.get(
                                projects_url, headers=headers
                            )
                            projects_resp.raise_for_status()
                            projects = projects_resp.json().get("value", [])

                            for project in projects:
                                project_name = project.get("name")
                                project_tags = project.get("tags", {})
                                props = project.get("properties", {})
                                endpoints = props.get("endpoints", {})
                                api_endpoint = endpoints.get("AI Foundry API")

                                # Apply tag filter if configured
                                if PROJECT_TAG_FILTER:
                                    if PROJECT_TAG_FILTER not in project_tags:
                                        logger.debug(
                                            f"    Skipping project {project_name} (missing tag: {PROJECT_TAG_FILTER})"
                                        )
                                        continue

                                all_projects.append(
                                    {
                                        "subscription_id": sub_id,
                                        "subscription_name": sub_name,
                                        "resource_group": resource_group,
                                        "account_name": account_name,
                                        "account_location": account_location,
                                        "account_display_name": account_hidden_title,
                                        "project_name": project_name,
                                        "project_location": project.get("location"),
                                        "endpoint": api_endpoint,
                                    }
                                )

                                logger.info(f"    Project: {project_name}")

                        except Exception as e:
                            logger.warning(
                                f"    Failed to list projects for {account_name}: {e}"
                            )
                            continue

                except Exception as e:
                    logger.warning(f"Failed to list accounts in {sub_name}: {e}")
                    continue

            return all_projects

    def process_approval(self, item, input_list=[]):
        if item.type == "mcp_approval_request":
            print(
                f"\n\n🔐 MCP approval requested: {item.name if hasattr(item, 'name') else 'tool'}"
            )
            input_list.append(
                McpApprovalResponse(
                    type="mcp_approval_response",
                    approve=True,
                    approval_request_id=item.id,
                )
            )

    async def process_response(self, response: Response) -> ProcessedResponse:
        """Process response and handle MCP approval requests."""
        result = ProcessedResponse(usage=response.to_dict().get("usage", {}))

        if response.status == "incomplete":
            print(f"⚠️ Response incomplete! Reason: {response.incomplete_details}")
        else:
            print(f"✅ Response complete with status: {response.status}.")

        for event in response.output:
            previous_event = (
                result.events_received[-1] if len(result.events_received) > 0 else None
            )
            if previous_event and previous_event["type"] == event.type:
                previous_event["count"] += 1
            else:
                result.events_received.append({"type": event.type, "count": 1})

            if event.type == "response.created":
                print(f"🆕 Stream started (ID: {event.response.id})\n")
            elif event.type == "response.output_text.delta":
                print(event.delta, end="", flush=True)
            elif event.type == "reasoning":
                reasoning_item: ResponseReasoningItem = event
                print(
                    f"🧠 Reasoning update ({reasoning_item.status}): {reasoning_item.content} Summary: {reasoning_item.summary}"
                )
            elif event.type == "bing_grounding_call":
                print(f"🔎 Bing grounding call: {event.arguments}")
            elif event.type == "bing_grounding_call_output":
                print("📥 Bing grounding call completed")
            elif event.type == "response.text.done":
                print("\n\n✅ Text complete")
            elif event.type == "response.output_item.added":
                if event.item.type == "mcp_approval_request":
                    self.process_approval(event.item, result.input_list)
                else:
                    print(f"\n\n📦 Output item added: {event.item.type}")
            elif event.type == "mcp_approval_request":
                self.process_approval(event, result.input_list)
            elif event.type == "response.output_item.done":
                print(f"   ✅ Item complete: {event.item.type}")
            elif event.type == "response.completed":
                result.response_id = event.response.id
                print("\n🎉 Response completed!")
                print(f"💰 Usage: {event.response.to_dict()['usage']}")
                result.full_response = event.response.output_text
            elif event.type == "mcp_list_tools":
                print("🔧 Listing tools...")
            elif event.type == "mcp_call":
                print(
                    f"🔧 Making MCP call to {event.name} on server {event.server_label} with arguments {event.arguments[:50]}. Result: '{event.output[:50]}'"
                )
            elif event.type == "message":
                for message in event.content:
                    if isinstance(message, ResponseOutputText):
                        result.full_response += message.text
                    for annotation in message.annotations:
                        print(f"💬 Message annotation: {annotation}")

        return result
