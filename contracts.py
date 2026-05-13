from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StrategyResult:
    should_open: bool = False
    signal: Optional[str] = None
    setup_type: Optional[str] = None
    score: int = 0
    args_text: str = ""
    blocked_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WatchlistItem:
    symbol: str
    price: float
    market: str
    score: int
    setup_type: str
    args_text: str
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PlannerIdeaContract:
    symbol: str
    current_price: float
    entry_zone: List[float] = field(default_factory=list)
    avg_entry: float = 0.0
    rr: float = 0.0
    confidence: int = 0
    risk: str = "medium"
    invalid_level: float = 0.0
    tp_base: float = 0.0
    tp_bull: float = 0.0
    reasons: List[str] = field(default_factory=list)
    ready: bool = False
    blocked_reason: Optional[str] = None
    setup_type: str = ""
    horizon: str = ""
    action: str = ""

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


@dataclass
class ExecutionResponse:
    code: str = "ERROR"
    msg: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HealthState:
    status: str = "offline"
    mode: str = "PAPER"
    uptime: str = ""
    ping_ms: str = "0"
    market_age_sec: float = 9999.0
    ta_age_sec: float = 9999.0
    server_time: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeSnapshot:
    mode: str = "PAPER"
    balances: Dict[str, float] = field(default_factory=lambda: {"fut": 0.0, "spot": 0.0})
    fut_position: Optional[Dict[str, Any]] = None
    spot_positions: Dict[str, Any] = field(default_factory=dict)
    ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)