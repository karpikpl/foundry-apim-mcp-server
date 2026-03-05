// ---------------------------------------------------------------------------
// Deploy the MCP Server container app with a user-assigned managed identity
// and the required RBAC role assignments.
//
// Prerequisites:
//   - An existing Container Apps Environment
//   - An existing Application Insights instance
//   - An existing AI Foundry account (for role assignments)
//   - The Docker image published to ghcr.io
// ---------------------------------------------------------------------------
targetScope = 'resourceGroup'

// ── Parameters ──────────────────────────────────────────────────
param location string = resourceGroup().location
param tags object = {}

@description('Resource ID of the existing Container Apps Environment.')
param containerAppsEnvironmentResourceId string

@description('Application Insights connection string for telemetry.')
param applicationInsightsConnectionString string

@description('GHCR image tag to deploy (e.g. ghcr.io/karpikpl/foundry-apim-mcp-server:latest).')
param imageName string = 'ghcr.io/karpikpl/foundry-apim-mcp-server:latest'

@description('Default model deployment name (e.g. gpt-5-mini). Leave empty to set at runtime.')
param defaultModelDeploymentName string = 'gpt-5-mini'

@description('Workload profile name for the Container App.')
param workloadProfileName string = 'Consumption'

var resourceToken = toLower(uniqueString(resourceGroup().id, location))
var mcpServerAppName = 'mcp-server-${resourceToken}'

// ── Managed Identity ────────────────────────────────────────────
module identity './modules/iam/identity.bicep' = {
  name: 'mcp-server-identity-${resourceToken}'
  params: {
    tags: tags
    location: location
    identityName: 'mcp-server-${resourceToken}-identity'
  }
}

// ── Role Assignments ────────────────────────────────────────────

// Cognitive Services OpenAI User on the AI Foundry account (data plane access)
module subscriptionAIUser './modules/iam/subscription-ai-user.bicep' = {
  name: 'mcp-role-openai-user-${resourceToken}'
  params: {
    principalId: identity.outputs.MANAGED_IDENTITY_PRINCIPAL_ID
  }
}

// Reader at subscription scope (for list_projects ARM management plane calls)
module subscriptionReader './modules/iam/subscription-reader.bicep' = {
  name: 'mcp-role-sub-reader-${resourceToken}'
  scope: subscription()
  params: {
    principalId: identity.outputs.MANAGED_IDENTITY_PRINCIPAL_ID
  }
}

// ── Container App ───────────────────────────────────────────────
module mcpServer './modules/aca/container-app.bicep' = {
  name: 'mcp-server-app-${resourceToken}'
  params: {
    tags: tags
    location: location
    name: mcpServerAppName
    workloadProfileName: workloadProfileName
    applicationInsightsConnectionString: applicationInsightsConnectionString
    containerAppsEnvironmentResourceId: containerAppsEnvironmentResourceId
    existingImage: imageName
    userAssignedManagedIdentityClientId: identity.outputs.MANAGED_IDENTITY_CLIENT_ID
    userAssignedManagedIdentityResourceId: identity.outputs.MANAGED_IDENTITY_RESOURCE_ID
    ingressTargetPort: 8000
    ingressExternal: true
    cpu: '0.5'
    memory: '1.0Gi'
    scaleMinReplicas: 1
    scaleMaxReplicas: 3
    definition: {
      settings: [
        {
          name: 'AUTH_MODE'
          value: 'default_credential'
        }
        {
          name: 'MCP_HOST'
          value: '0.0.0.0'
        }
        {
          name: 'MCP_PORT'
          value: '8000'
        }
        {
          name: 'AZURE_OPENAI_CHAT_DEPLOYMENT_NAME'
          value: defaultModelDeploymentName
        }
      ]
    }
    probes: [
      {
        type: 'Startup'
        initialDelaySeconds: 3
        periodSeconds: 5
        failureThreshold: 10
        tcpSocket: {
          port: 8000
        }
      }
      {
        type: 'Liveness'
        initialDelaySeconds: 10
        periodSeconds: 30
        tcpSocket: {
          port: 8000
        }
      }
    ]
  }
}

// ── Outputs ─────────────────────────────────────────────────────
output MCP_SERVER_URL string = mcpServer.outputs.CONTAINER_APP_FQDN
output MCP_SERVER_ENDPOINT string = '${mcpServer.outputs.CONTAINER_APP_FQDN}/mcp'
output MANAGED_IDENTITY_PRINCIPAL_ID string = identity.outputs.MANAGED_IDENTITY_PRINCIPAL_ID
output MANAGED_IDENTITY_CLIENT_ID string = identity.outputs.MANAGED_IDENTITY_CLIENT_ID
