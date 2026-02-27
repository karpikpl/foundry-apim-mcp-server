"""OAuth bearer token credential adapter for Azure SDK."""

from azure.core.credentials import AccessToken as AzureAccessToken
from azure.core.credentials_async import AsyncTokenCredential
import time


class BearerTokenCredential(AsyncTokenCredential):
    """Wraps a raw OAuth bearer token into an Azure AsyncTokenCredential.

    The MCP client passes a bearer token (obtained via OAuth against Entra ID).
    This adapter makes it usable by the Azure AI Projects SDK.
    """

    def __init__(self, token: str, expires_in: int = 3600):
        self._token = token
        self._expires_on = int(time.time()) + expires_in

    async def get_token(self, *scopes, **kwargs) -> AzureAccessToken:
        return AzureAccessToken(self._token, self._expires_on)

    async def close(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
