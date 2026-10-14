# SPDX-License-Identifier: AGPL-3.0-or-later
"""The providers 234 has, and how a merchant or a quote finds its own. A merchant id names one merchant in the
whole directory: the first provider that lists an id owns it."""

from ..errors import DomainError
from .model import Merchant
from .provider import Provider


class Providers:
    def __init__(self, *providers: Provider) -> None:
        names = [provider.name for provider in providers]
        if len(set(names)) != len(names):
            raise ValueError("Two providers have the same name.")
        self._providers = {provider.name: provider for provider in providers}

    async def merchants(self, category: str | None = None) -> list[Merchant]:
        """Every provider's merchants, each provider's in its own order."""
        return [m for provider in self._providers.values() for m in await provider.merchants(category)]

    async def merchant(self, merchant_id: str) -> Merchant:
        for provider in self._providers.values():
            found = await provider.merchant(merchant_id)
            if found is not None:
                return found
        raise DomainError(
            "MERCHANT_NOT_FOUND",
            f'There is no merchant "{merchant_id}" in the directory. A quote needs a merchant_id from '
            "browse_merchants; if the business is not listed, tell the person 234 cannot pay it yet.",
        )

    def of(self, merchant: Merchant) -> Provider:
        return self._providers[merchant.provider]

    def named(self, provider: str) -> Provider:
        found = self._providers.get(provider)
        if found is None:
            raise DomainError("PROVIDER_UNAVAILABLE", f"The provider {provider} is not offered here.")
        return found
