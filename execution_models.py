from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


@dataclass
class OpenRequestFutures:
    symbol: str
    side: str
    qty: float
    price: float
    tp: float
    sl: float
    atr: float
    leverage: float = 3.0
    setup_type: str = ""
    args_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OpenRequestSpot:
    symbol: str
    qty: float
    price: float
    tp: float
    atr: float
    setup_type: str = ""
    args_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CloseRequest:
    symbol: str
    market: str
    current_price: float
    reason: str = "MANUAL"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PositionSnapshot:
    symbol: str
    market: str
    side: Optional[str] = None
    qty: float = 0.0
    entry: float = 0.0
    avg_price: float = 0.0
    mark_price: float = 0.0
    tp: Optional[float] = None
    tp2: Optional[float] = None
    sl: Optional[float] = None
    trail_sl: Optional[float] = None
    atr: Optional[float] = None
    leverage: Optional[float] = None
    liq_price: Optional[float] = None
    pnl: float = 0.0
    pnl_net: float = 0.0
    tp1_hit: bool = False
    breakeven: bool = False
    fills_count: int = 1
    status_label: str = "OPEN"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionResponse:
    code: str = "ERROR"
    msg: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionEvent:
    event_type: str
    symbol: str
    market: str
    reason: str
    message: str = ""
    pnl: float = 0.0
    pnl_net: float = 0.0
    price: float = 0.0
    ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)