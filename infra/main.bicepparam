using './main.bicep'

param containerAppsEnvironmentResourceId = readEnvironmentVariable('CONTAINER_APPS_ENVIRONMENT_RESOURCE_ID', '')
param applicationInsightsConnectionString = readEnvironmentVariable('APPLICATION_INSIGHTS_CONNECTION_STRING', '')
param imageName = 'ghcr.io/karpikpl/foundry-apim-mcp-server:latest'
param defaultModelDeploymentName = 'gpt-5-mini'
param workloadProfileName = 'Consumption'
