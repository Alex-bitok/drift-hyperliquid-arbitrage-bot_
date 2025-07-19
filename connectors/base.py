from abc import ABC, abstractmethod
from typing import Any, Dict

class ConnectorBase(ABC):
    """Base connector interface for exchanges."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abstractmethod
    async def fetch_book(self, symbol: str) -> Dict[str, Any]:
        """Return current order book snapshot."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_funding(self, symbol: str) -> Dict[str, Any]:
        """Return current funding information."""
        raise NotImplementedError

    @abstractmethod
    async def place_order(
        self, symbol: str, side: str, amount: float, price: float
    ) -> Any:
        """Place an order and return exchange-specific id."""

    @abstractmethod
    async def cancel_order(self, order_id: Any) -> None:
        """Cancel an existing order."""

    @abstractmethod
    async def get_position(self, symbol: str) -> Dict[str, Any]:
        """Return current position information."""
