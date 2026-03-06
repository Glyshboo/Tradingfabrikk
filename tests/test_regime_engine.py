from packages.core.models import MarketSnapshot, Regime
from packages.selector.regime_engine import RegimeEngine


def test_regime_engine_detects_high_vol_and_illiquid_first():
    engine = RegimeEngine()
    illiquid = MarketSnapshot(symbol="BTCUSDT", price=100, bid=99.8, ask=100.2, atr=1.0, rsi=50)
    assert engine.classify(illiquid) == Regime.ILLIQUID

    high_vol = MarketSnapshot(symbol="BTCUSDT", price=100, bid=99.99, ask=100.01, atr=3.5, rsi=52)
    assert engine.classify(high_vol) == Regime.HIGH_VOL


def test_regime_engine_uses_rsi_and_momentum_for_trend():
    engine = RegimeEngine()
    trend_up = MarketSnapshot(symbol="BTCUSDT", price=101, bid=100.98, ask=101.02, candle_close=100, atr=1.2, rsi=60)
    trend_down = MarketSnapshot(symbol="BTCUSDT", price=99, bid=98.98, ask=99.02, candle_close=100, atr=1.2, rsi=40)
    assert engine.classify(trend_up) == Regime.TREND_UP
    assert engine.classify(trend_down) == Regime.TREND_DOWN
