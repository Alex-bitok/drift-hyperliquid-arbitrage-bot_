from .base import ArbitrageStrategyBase
from .basis import BasisStrategy
from .funding import FundingStrategy

STRATEGY_MAP = {
    'basis': BasisStrategy,
    'funding': FundingStrategy,
}

__all__ = [
    'ArbitrageStrategyBase',
    'BasisStrategy',
    'FundingStrategy',
    'STRATEGY_MAP',
]
