// ---------------------------------------------------------------------------
// Subscription-scoped Reader role assignment.
// Separated into its own file because it targets subscription scope.
// ---------------------------------------------------------------------------
targetScope = 'subscription'

@description('Principal ID to assign the Reader role to.')
param principalId string

var readerRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'acdd72a7-3385-48ef-bd42-f606fba81ae7' // Reader built-in role
)

resource readerRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(principalId, readerRoleDefinitionId, subscription().id)
  properties: {
    principalId: principalId
    roleDefinitionId: readerRoleDefinitionId
    principalType: 'ServicePrincipal'
  }
}
