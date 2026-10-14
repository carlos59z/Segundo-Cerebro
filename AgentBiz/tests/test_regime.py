import numpy as np
import pandas as pd
import pytest

import regime


def test_efficiency_ratio_tendencia_perfecta():
    close = pd.Series(np.linspace(100, 110, 6))
    er = regime.efficiency_ratio(close, n=5)
    assert er.iloc[-1] == pytest.approx(1.0)


def test_efficiency_ratio_zigzag_es_cero():
    # ida y vuelta que termina donde empieza -> direccion neta 0
    close = pd.Series([100.0, 110.0, 100.0, 110.0, 100.0, 100.0])
    er = regime.efficiency_ratio(close, n=5)
    assert er.iloc[-1] == pytest.approx(0.0)


def test_efficiency_ratio_warmup_nan():
    close = pd.Series(np.linspace(100, 110, 10))
    er = regime.efficiency_ratio(close, n=5)
    assert np.isnan(er.iloc[4])
    assert not np.isnan(er.iloc[5])


def test_trend_regime_sma200():
    close = pd.Series(np.concatenate([np.full(200, 100.0),
                                      np.linspace(100, 150, 50)]))
    r = regime.trend_regime(close, method="sma200", window=200)
    assert not r.iloc[199]  # planicie: close == sma
    assert not r.iloc[150]
    assert r.iloc[-1]       # tramo alcista final


def test_trend_regime_er():
    close = pd.Series(np.concatenate([np.full(30, 100.0),
                                      np.linspace(100, 150, 30)]))
    r = regime.trend_regime(close, method="er", window=10, threshold=0.3)
    assert not r.iloc[15]  # planicie (ruido cero -> ER NaN -> False)
    assert r.iloc[-1]      # tendencia fuerte


def test_vol_target_scale_escala_a_target():
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0, 0.01, 100))  # vol diaria ~1% -> ~15.9% anual
    realized = r.rolling(20).std().iloc[-1] * np.sqrt(252)
    s = regime.vol_target_scale(r, target_annual=realized, window=20,
                                min_scale=0.25, max_scale=2.0)
    assert s.iloc[-1] == pytest.approx(1.0, abs=0.01)


def test_vol_target_scale_limites():
    r = pd.Series([0.0] * 30)
    s = regime.vol_target_scale(r, target_annual=0.15, window=20,
                                min_scale=0.25, max_scale=2.0)
    assert s.iloc[-1] == 2.0  # vol ~0 -> techo
    r2 = pd.Series([0.10, -0.10] * 20)
    s2 = regime.vol_target_scale(r2, target_annual=0.15, window=20,
                                 min_scale=0.25, max_scale=2.0)
    assert s2.iloc[-1] == 0.25  # vol enorme -> piso


def test_vol_target_scale_warmup_neutral():
    r = pd.Series(np.full(30, 0.01))
    s = regime.vol_target_scale(r, target_annual=0.15, window=20)
    assert s.iloc[5] == 1.0
