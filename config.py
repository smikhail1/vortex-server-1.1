from dataclasses import dataclass, field
from typing import Dict, List

@dataclass(frozen=True)
class ExchangeIntelConfig:
    enabled: bool = True
    update_sec: int = 60
    funding_extreme_long: float = 0.003
    funding_long: float = 0.001
    funding_short: float = -0.0005
    funding_extreme_short: float = -0.001
    oi_change_threshold_pct: float = 3.0
    oi_trend_bonus: int = 1
    funding_bias_penalty: int = 1

class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    cors_allow_all: bool = True

@dataclass(frozen=True)
class LoopIntervals:
    market_data_sec: float = 1.0
    pool_rotation_sec: float = 30.0
    candle_sec: float = 60.0
    ta_sec: float = 5.0
    system_metrics_sec: float = 5.0
    monitor_sec: float = 10.0
    router_sync_sec: float = 1.0
    planner_market_sec: float = 600.0
    planner_sec: float = 120.0
    watchlist_sec: float = 5.0
    strategy_sec: float = 5.0
    execution_sec: float = 1.0
    oracle_sec: float = 10.0
    safe_loop_backoff_sec: float = 2.0

@dataclass(frozen=True)
class UniverseConfig:
    enabled: bool = True
    refresh_sec: int = 30
    dynamic_enabled: bool = True
    dynamic_universe_enabled: bool = True
    top_n: int = 160  # v1.8.7 dynamic active pool
    fut_pool_size: int = 60  # v1.8.7 dynamic active pool
    spot_pool_size: int = 15  # v1.8.7 dynamic active pool
    # Поднимаем порог объема, чтобы отсечь неликвид:
    min_quote_volume_usdt: float = 3_000_000.0  # v1.8.7 dynamic active pool
    min_last_price: float = 0.01
    max_last_price: float = 1_000_000.0
    min_24h_range_pct: float = 0.8
    max_24h_range_pct: float = 25.0
    min_24h_change_abs_pct: float = 0.5
    rank_weight_volume: float = 0.35
    rank_weight_range: float = 0.40
    rank_weight_change: float = 0.25
    exclude_stables: bool = True
    exclude_leveraged_tokens: bool = True
    exclude_fiat_pairs: bool = True
    blacklisted_symbols: List[str] = field(
        default_factory=lambda: [
            "SPKUSDT", "CHIPUSDT", "MAGICUSDT", "1000BONKUSDT",
            "1000FLOKIUSDT", "1000SHIBUSDT", "1000PEPEUSDT",
            "XAUUSDT", "XAGUSDT", "XAUTUSDT", "PAXGUSDT",
            "TSLAUSDT", "NVDAUSDT", "INTCUSDT", "MSTRUSDT",
            "CRCLUSDT", "HOODUSDT", "TRUMPUSDT", "RAVEUSDT",
            "ENSOUSDT", "NAORISUSDT",
        ]
    )
    fallback_symbols: List[str] = field(
        default_factory=lambda: [
            'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT',
            'BNBUSDT', 'ADAUSDT', 'AVAXUSDT', 'LINKUSDT', 'LTCUSDT',
            'TRXUSDT', 'DOTUSDT', 'BCHUSDT', 'NEARUSDT', 'APTUSDT',
            'ARBUSDT', 'OPUSDT', 'INJUSDT', 'SEIUSDT', 'ATOMUSDT',
            'FILUSDT', 'ETCUSDT', 'AAVEUSDT', 'UNIUSDT', 'SANDUSDT',
            'MANAUSDT', 'GALAUSDT', 'APEUSDT', 'PEOPLEUSDT', 'DYDXUSDT',
            'GMTUSDT', 'CHZUSDT', 'CRVUSDT', 'ALGOUSDT', 'VETUSDT',
            'ICPUSDT', 'EGLDUSDT', 'SUSHIUSDT', 'COMPUSDT', 'MKRUSDT',
            'LDOUSDT', 'MAGICUSDT', 'CFXUSDT', 'STXUSDT', 'BLURUSDT',
            'WLDUSDT', 'TIAUSDT', 'ORDIUSDT', 'JUPUSDT', 'PYTHUSDT',
            'STRKUSDT', 'WIFUSDT', 'ENAUSDT', 'TONUSDT', 'ZECUSDT',
            'HYPEUSDT', 'MUUSDT', 'CLUSDT', 'BILLUSDT', 'SNDKUSDT',
            '1000PEPEUSDT', '1000SHIBUSDT', '1000FLOKIUSDT',
        ]
    )
    excluded_base_assets: List[str] = field(
        default_factory=lambda: [
            "USDC", "FDUSD", "TUSD", "BUSD", "USDP", "DAI", "EUR",
            "EURS", "GBP", "TRY", "BRL", "UAH", "RUB", "AUD", "JPY",
            "USD1", "PYUSD", "USDE", "USDD", "FRAX", "MIM", "RLUSD",
            "XAUT", "PAXG",
        ]
    )

@dataclass(frozen=True)
class TradingConfig:
    mode: str = "PAPER"
    futures_margin_usdt: float = 1.0  # v1.8.19e research mode
    spot_order_usdt: float = 20.0
    futures_default_leverage: float = 3.0
    futures_min_score_to_open: int = 7
    spot_min_score_to_open: int = 6
    watchlist_min_score: int = 6
    watchlist_display_limit: int = 40  # v1.8.7 UI/active watchlist expansion
    futures_watch_ttl_sec: int = 21600
    spot_watch_ttl_sec: int = 172800
    futures_confirmation_buffer_atr: float = 0.18
    spot_confirmation_buffer_atr: float = 0.10
    spot_entry_1_pct: float = 0.60
    spot_entry_2_pct: float = 0.40
    allow_manual_trades: bool = True
    allow_force_close: bool = False
    allow_risk_reset: bool = False
    debug_api_enabled: bool = True

@dataclass(frozen=True)
class RiskConfig:
    futures_symbol_cooldown_sec: int = 3600
    spot_symbol_cooldown_sec: int = 1800
    max_trades_per_symbol_per_day: int = 5
    daily_loss_limit_usdt: float = -5.0
    max_open_futures_positions: int = 4  # v1.8.19e research mode: multi paper futures telemetry
    max_open_spot_positions: int = 5
    loss_streak_limit: int = 3
    loss_streak_cooldown_sec: int = 14400
    persistence_enabled: bool = True
    persistence_path: str = "risk_state.json"

@dataclass(frozen=True)
class PositionStateConfig:
    enabled: bool = True
    max_events_per_position: int = 80
    max_closed_positions: int = 100

@dataclass(frozen=True)
class PaperFuturesConfig:
    start_balance: float = 100.0
    taker_fee: float = 0.0006
    maker_fee: float = 0.0002
    spread_bps: float = 4.0
    slippage_bps: float = 2.0
    maintenance_margin_rate: float = 0.005
    profit_timeout_sec: int = 3600
    tp1_stall_sec: int = 900
    min_timeout_profit_usdt: float = 0.15
    fade_giveback_pct: float = 0.72
    trailing_atr_mult: float = 1.5
    futures_tp2_atr_mult: float = 5.0
    momentum_tp2_atr_mult: float = 3.5

@dataclass(frozen=True)
class PositionGuideConfig:
    enabled: bool = True
    # Отодвигаем перевод в безубыток:
    be_trigger_usdt: float = 0.25
    be_min_hold_sec: int = 180
    trail_trigger_usdt: float = 0.35
    trail_atr_mult: float = 1.50
    fade_min_max_pnl_usdt: float = 0.20
    fade_keep_ratio: float = 0.55
    profit_timeout_sec: int = 3600
    profit_timeout_min_pnl_usdt: float = 0.10
    setup_died_enabled: bool = True
    setup_died_min_hold_sec: int = 600
    setup_died_score_lt: int = 4
    early_bad_enabled: bool = True
    early_bad_min_hold_sec: int = 300
    early_bad_pnl_lt_usdt: float = -0.12
    early_bad_score_lt: int = 4

@dataclass(frozen=True)
class PaperSpotConfig:
    start_balance: float = 100.0
    taker_fee: float = 0.001
    maker_fee: float = 0.0008
    spread_bps: float = 4.0
    slippage_bps: float = 2.0
    profit_timeout_sec: int = 900
    tp1_stall_sec: int = 600
    min_timeout_profit_usdt: float = 0.10
    fade_giveback_pct: float = 0.65

@dataclass(frozen=True)
class StrategyConfig:
    ema_filter_enabled: bool = True
    volume_filter_enabled: bool = True
    min_vol_ratio_futures: float = 1.10
    min_vol_ratio_spot: float = 1.05
    futures_tp_atr_mult: float = 3.2
    # Даем больше кислорода основному стопу:
    futures_sl_atr_mult: float = 2.2
    futures_tp2_atr_mult: float = 5.0
    momentum_tp2_atr_mult: float = 3.5
    spot_tp_atr_mult: float = 3.0
    spot_sl_atr_mult: float = 2.0
    long_rsi_min: float = 45.0
    short_rsi_max: float = 55.0
    fee_guard_enabled: bool = True
    futures_fee_edge_multiplier: float = 2.2
    spot_fee_edge_multiplier: float = 2.6
    futures_min_expected_net_usdt: float = 0.03
    spot_min_expected_net_usdt: float = 0.08

@dataclass(frozen=True)
class MomentumConfig:
    enabled: bool = True
    min_range_pct: float = 5.0
    min_change_abs_pct: float = 3.0
    min_vol_ratio: float = 1.25
    strong_range_pct: float = 9.0
    strong_change_abs_pct: float = 5.0
    strong_vol_ratio: float = 1.6
    watch_score: int = 5
    confirm_score: int = 7
    macro_override_score: int = 10
    trigger_atr_buffer: float = 0.10
    invalidation_atr_mult: float = 1.25
    long_rsi_min: float = 52.0
    short_rsi_max: float = 48.0
    tp_atr_mult: float = 3.0
    # Отдаляем импульсный стоп-лосс:
    sl_atr_mult: float = 2.0
    allow_spot_momentum: bool = False
    quality_filter_enabled: bool = True
    max_ema_distance_pct: float = 8.0
    max_ema_distance_atr: float = 5.0
    max_quality_range_pct: float = 22.0
    max_quality_change_abs_pct: float = 18.0
    long_rsi_exhaustion: float = 78.0
    short_rsi_exhaustion: float = 22.0
    quality_filter_blocks_breakouts: bool = True

@dataclass(frozen=True)
class CandleConfig:
    enabled: bool = True
    interval_30m: str = "5m"
    interval_4h: str = "4H"
    limit_30m: int = 120
    limit_4h: int = 120
    refresh_sec: int = 60
    request_timeout_sec: int = 10
    max_concurrency: int = 6

@dataclass(frozen=True)
class RegimeConfig:
    min_history_bars: int = 20
    strong_trend_ema_gap_pct: float = 0.35
    weak_trend_ema_gap_pct: float = 0.12
    breakout_buffer_atr: float = 0.08
    retest_buffer_atr: float = 0.35
    pullback_zone_buffer_pct: float = 0.0025
    pullback_ema50_tolerance_pct: float = 0.006
    min_workable_atr_pct: float = 0.7
    max_bad_atr_pct: float = 4.0
    vol_spike_threshold: float = 1.5
    breakout_volume_threshold: float = 1.2
    trend_volume_threshold: float = 1.0
    macro_fng_riskoff_threshold: int = 35
    macro_fng_riskon_threshold: int = 60

@dataclass(frozen=True)
class PlannerConfig:
    enabled: bool = True
    max_ideas: int = 12
    dynamic_universe_from_pool: bool = True  # v1.8.7b planner uses active pool
    dynamic_universe_limit: int = 40  # v1.8.7b max symbols per planner snapshot
    dynamic_universe_include_spot: bool = True  # v1.8.7b merge spot pool after futures
    snapshot_universe: List[str] = field(
        default_factory=lambda: [
            'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT',
            'BNBUSDT', 'ADAUSDT', 'AVAXUSDT', 'LINKUSDT', 'LTCUSDT',
            'TRXUSDT', 'DOTUSDT', 'BCHUSDT', 'NEARUSDT', 'APTUSDT',
            'ARBUSDT', 'OPUSDT', 'INJUSDT', 'SEIUSDT', 'ATOMUSDT',
            'FILUSDT', 'ETCUSDT', 'AAVEUSDT', 'UNIUSDT', 'SANDUSDT',
            'MANAUSDT', 'GALAUSDT', 'APEUSDT', 'PEOPLEUSDT', 'DYDXUSDT',
            'GMTUSDT', 'CHZUSDT', 'CRVUSDT', 'ALGOUSDT', 'VETUSDT',
            'ICPUSDT', 'EGLDUSDT', 'SUSHIUSDT', 'COMPUSDT', 'MKRUSDT',
            'LDOUSDT', 'CFXUSDT', 'STXUSDT', 'BLURUSDT', 'WLDUSDT',
            'TIAUSDT', 'ORDIUSDT', 'JUPUSDT', 'PYTHUSDT', 'STRKUSDT',
            'WIFUSDT', 'ENAUSDT', 'TONUSDT', 'ZECUSDT', 'HYPEUSDT',
            'SUIUSDT', 'MUUSDT', 'CLUSDT', 'SNDKUSDT',
        ]
    )

@dataclass(frozen=True)
class LoggingConfig:
    runtime_log_path: str = "vortex.log"
    trades_csv_path: str = "trades.csv"
    max_sys_logs: int = 300
    print_to_stdout: bool = True

@dataclass(frozen=True)
class AppConfig:
    server: ServerConfig = ServerConfig()
    loops: LoopIntervals = LoopIntervals()
    universe: UniverseConfig = UniverseConfig()
    exchange_intel: ExchangeIntelConfig = ExchangeIntelConfig()
    trading: TradingConfig = TradingConfig()
    risk: RiskConfig = RiskConfig()
    position_state: PositionStateConfig = PositionStateConfig()
    position_guide: PositionGuideConfig = PositionGuideConfig()
    futures: PaperFuturesConfig = PaperFuturesConfig()
    spot: PaperSpotConfig = PaperSpotConfig()
    strategy: StrategyConfig = StrategyConfig()
    momentum: MomentumConfig = MomentumConfig()
    candles: CandleConfig = CandleConfig()
    regime: RegimeConfig = RegimeConfig()
    planner: PlannerConfig = PlannerConfig()
    logging: LoggingConfig = LoggingConfig()

CONFIG = AppConfig()

DEFAULT_STATE_META: Dict[str, str] = {
    "version": "1.6.5",
    "compatibility": "android-vortex-terminal",
    "mode": CONFIG.trading.mode,
}
