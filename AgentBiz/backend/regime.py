"""Filtros de régimen de mercado y dimensionamiento por volatilidad.

- efficiency_ratio (Kaufman): direccion/ruido; 1=tendencia pura, 0=ruido.
- trend_regime: True cuando el régimen favorece estrategias de tendencia.
- vol_target_scale: multiplicador que acerca la vol anualizada al target.
"""
import numpy as np
import pandas as pd

TRADING_DAYS = 252


def efficiency_ratio(close, n=20):
    delta = close.diff().abs()
    direction = (close - close.shift(n)).abs()
    noise = delta.rolling(n).sum()
    return direction / noise.replace(0.0, np.nan)


def trend_regime(close, method="er", window=20, threshold=0.3):
    if method == "sma200":
        sma = close.rolling(window).mean()
        return (close > sma).fillna(False)
    if method == "er":
        er = efficiency_ratio(close, n=window)
        return (er > threshold).fillna(False)
    raise ValueError(f"metodo de regime desconocido: {method}")


def vol_target_scale(returns, target_annual=0.15, window=20,
                     min_scale=0.25, max_scale=2.0):
    realized = returns.rolling(window).std() * np.sqrt(TRADING_DAYS)
    with np.errstate(divide="ignore", invalid="ignore"):
        scale = target_annual / realized
    scale = scale.replace([np.inf, -np.inf], max_scale)
    scale = scale.clip(lower=min_scale, upper=max_scale)
    return scale.fillna(1.0)
