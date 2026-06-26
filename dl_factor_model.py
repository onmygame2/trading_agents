"""
深度学习因子选股 — 纯 NumPy MLP（零 PyTorch 依赖）

架构: 36维因子 → 64 → 32 → sigmoid
标签: 未来5日收益 > 1%
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ml_models")
MODEL_FILE = "dl_factor_mlp.npz"
META_FILE = "dl_factor_meta.json"

FEATURE_NAMES: List[str] = [
    "trend", "fundamental", "valuation", "sector", "capital", "momentum",
    "total_score",
    "rsi", "macd_dif", "macd_hist", "vol_ratio", "change_pct",
    "mom_5d", "mom_10d", "mom_20d", "volatility", "price_pos", "boll_width",
    "ma_bull", "break_60d", "macd_golden",
    "pe", "pb", "roe", "market_cap", "yoy_ni", "gp_margin",
    "north_flow", "turnover", "price_vs_ma20",
    "pos_in_day", "has_limit_up_180d", "limit_up_count_180d",
    "sector_change", "index_change", "sentiment",
]


def _fval(v, default=0.0) -> float:
    try:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def extract_features(
    stock: Dict,
    sector_data: Dict = None,
    market_ctx: Dict = None,
) -> np.ndarray:
    dims = stock.get("dimensions", {})
    pv = stock.get("price_volume", {}) or {}
    fund = stock.get("fundamental", {}) or stock.get("fund", {}) or {}
    extra = stock.get("extra", {}) or {}

    industry = stock.get("industry", "")
    sector_chg = 0.0
    if sector_data and industry:
        for sec in sector_data.get("hot_sectors", []):
            if sec.get("name") == industry:
                sector_chg = _fval(sec.get("change_pct"))
                break

    ctx = market_ctx or {}
    high = _fval(pv.get("today_high"))
    low = _fval(pv.get("today_low"))
    close = _fval(pv.get("price"))
    pos_in_day = (close - low) / (high - low) if high > low > 0 else 0.5

    vec = [
        _fval((dims.get("trend") or {}).get("score", 50)),
        _fval((dims.get("fundamental") or {}).get("score", 50)),
        _fval((dims.get("valuation") or {}).get("score", 50)),
        _fval((dims.get("sector") or {}).get("score", 50)),
        _fval((dims.get("capital") or {}).get("score", 50)),
        _fval((dims.get("momentum") or {}).get("score", 50)),
        _fval(stock.get("total_score", 50)),
        _fval(pv.get("rsi", 50)),
        _fval(pv.get("macd_dif")),
        _fval(pv.get("macd_hist")),
        _fval(pv.get("vol_ratio", 1)),
        _fval(pv.get("change_pct")),
        _fval(pv.get("mom_5d")),
        _fval(pv.get("mom_10d")),
        _fval(pv.get("mom_20d")),
        _fval(pv.get("volatility")),
        _fval(pv.get("price_pos", 50)),
        _fval(pv.get("boll_width")),
        1.0 if pv.get("ma_bull") else 0.0,
        1.0 if pv.get("break_60d") else 0.0,
        1.0 if pv.get("macd_golden_cross") else 0.0,
        _fval(fund.get("pe") or fund.get("peTTM"), 30),
        _fval(fund.get("pb") or fund.get("pbMRQ"), 3),
        _fval(fund.get("roe") or fund.get("roeAvg")),
        _fval(extra.get("market_cap"), 100),
        _fval(fund.get("yoy_ni") or fund.get("YOYNI")),
        _fval(fund.get("gp_margin") or fund.get("gpMargin")),
        _fval(ctx.get("north_flow")),
        _fval(pv.get("turnover") or pv.get("turn")),
        _fval(pv.get("price_vs_ma20")),
        pos_in_day,
        1.0 if pv.get("has_limit_up_180d") else 0.0,
        _fval(pv.get("limit_up_count_180d")),
        sector_chg,
        _fval(ctx.get("index_change")),
        _fval(ctx.get("sentiment", 50)),
    ]
    return np.nan_to_num(np.array(vec, dtype=np.float64), nan=0.0, posinf=50.0, neginf=-50.0)


class NumPyMLP:
    def __init__(self, input_dim: int, hidden: Tuple[int, ...] = (64, 32), lr: float = 0.002, l2: float = 1e-4, dropout: float = 0.15):
        self.input_dim = input_dim
        self.hidden = hidden
        self.lr = lr
        self.l2 = l2
        self.dropout = dropout
        self.mean: Optional[np.ndarray] = None
        self.std: Optional[np.ndarray] = None
        self._init_weights()

    def _init_weights(self):
        layers = [self.input_dim] + list(self.hidden) + [1]
        self.W, self.b = [], []
        for i in range(len(layers) - 1):
            fan_in = layers[i]
            self.W.append(np.random.randn(fan_in, layers[i + 1]) * np.sqrt(2.0 / fan_in))
            self.b.append(np.zeros(layers[i + 1]))

    @staticmethod
    def _relu(x):
        return np.maximum(0, x)

    @staticmethod
    def _sigmoid(x):
        x = np.clip(x, -20, 20)
        return 1.0 / (1.0 + np.exp(-x))

    def _standardize(self, X, fit=False):
        if fit:
            self.mean = np.mean(X, axis=0)
            self.std = np.std(X, axis=0)
            self.std[self.std < 1e-6] = 1.0
        return (X - self.mean) / self.std

    def forward(self, X, train=False):
        cache = []
        h = X
        for W, b in zip(self.W[:-1], self.b[:-1]):
            z = h @ W + b
            a = self._relu(z)
            if train and self.dropout > 0:
                mask = (np.random.rand(*a.shape) > self.dropout).astype(np.float64)
                a = a * mask / (1 - self.dropout)
            cache.append((h, z, a))
            h = a
        z_out = h @ self.W[-1] + self.b[-1]
        out = self._sigmoid(z_out)
        cache.append((h, z_out, out))
        return out.reshape(-1), cache

    def predict_proba(self, X):
        X = self._standardize(X, fit=False)
        proba, _ = self.forward(X, train=False)
        return proba

    def fit(self, X, y, epochs=80, batch_size=256, val_ratio=0.2):
        X = self._standardize(X, fit=True)
        n = len(X)
        idx = np.random.permutation(n)
        split = int(n * (1 - val_ratio))
        tr_idx, va_idx = idx[:split], idx[split:]
        best_val, wait, best_W, best_b = 1e9, 0, None, None

        for epoch in range(epochs):
            perm = np.random.permutation(split)
            for start in range(0, split, batch_size):
                batch = perm[start : start + batch_size]
                xb, yb = X[batch], y[batch]
                proba, cache = self.forward(xb, train=True)
                proba = np.clip(proba, 1e-6, 1 - 1e-6)
                error = proba - yb
                grad_out = error / len(yb)
                h, z, out = cache[-1]
                dh = grad_out.reshape(-1, 1) * out.reshape(-1, 1) * (1 - out.reshape(-1, 1))
                self.W[-1] -= self.lr * (h.T @ dh + self.l2 * self.W[-1])
                self.b[-1] -= self.lr * np.mean(dh, axis=0)
                delta = dh @ self.W[-1].T
                for li in range(len(self.W) - 2, -1, -1):
                    h, z, a = cache[li]
                    dz = delta * (z > 0)
                    self.W[li] -= self.lr * (h.T @ dz + self.l2 * self.W[li])
                    self.b[li] -= self.lr * np.mean(dz, axis=0)
                    delta = dz @ self.W[li].T

            if len(va_idx) > 0:
                vp = np.clip(self.predict_proba(X[va_idx]), 1e-6, 1 - 1e-6)
                val_loss = -np.mean(y[va_idx] * np.log(vp) + (1 - y[va_idx]) * np.log(1 - vp))
                if val_loss < best_val:
                    best_val = val_loss
                    best_W = [w.copy() for w in self.W]
                    best_b = [b.copy() for b in self.b]
                    wait = 0
                else:
                    wait += 1
                    if wait >= 12:
                        break

        if best_W is not None:
            self.W, self.b = best_W, best_b

        train_acc = float(np.mean((self.predict_proba(X[tr_idx]) >= 0.5) == y[tr_idx]))
        val_acc = float(np.mean((self.predict_proba(X[va_idx]) >= 0.5) == y[va_idx])) if len(va_idx) else 0.0
        return {"train_acc": train_acc, "val_acc": val_acc, "epochs_run": epoch + 1}

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        payload = {"mean": self.mean, "std": self.std, "input_dim": self.input_dim, "n_layers": len(self.W)}
        for i, (w, b) in enumerate(zip(self.W, self.b)):
            payload[f"W{i}"] = w
            payload[f"b{i}"] = b
        np.savez(path, **payload)

    @classmethod
    def load(cls, path: str) -> "NumPyMLP":
        data = np.load(path)
        input_dim = int(data["input_dim"])
        n_layers = int(data["n_layers"])
        hidden = tuple(int(data[f"W{i}"].shape[1]) for i in range(n_layers - 1))
        m = cls(input_dim, hidden)
        m.mean = data["mean"]
        m.std = data["std"]
        m.W = [data[f"W{i}"] for i in range(n_layers)]
        m.b = [data[f"b{i}"] for i in range(n_layers)]
        return m


class DLFactorSelector:
    def __init__(self, model_dir: str = None):
        self.model_dir = model_dir or MODEL_DIR
        os.makedirs(self.model_dir, exist_ok=True)
        self.mlp: Optional[NumPyMLP] = None
        self.meta: Dict[str, Any] = {}

    @property
    def model_path(self) -> str:
        return os.path.join(self.model_dir, MODEL_FILE)

    @property
    def meta_path(self) -> str:
        return os.path.join(self.model_dir, META_FILE)

    def is_trained(self) -> bool:
        return os.path.exists(self.model_path)

    def build_matrix(self, stocks, sector_data=None, market_ctx=None):
        codes, rows = [], []
        for s in stocks:
            code = s.get("code")
            if not code:
                continue
            codes.append(code)
            rows.append(extract_features(s, sector_data, market_ctx))
        if not rows:
            return [], np.empty((0, len(FEATURE_NAMES)))
        return codes, np.vstack(rows)

    def train(self, X, y, epochs=80):
        self.mlp = NumPyMLP(len(FEATURE_NAMES), hidden=(64, 32))
        metrics = self.mlp.fit(X, y, epochs=epochs)
        self.meta = {
            "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "n_samples": len(X),
            "pos_rate": float(np.mean(y)),
            "feature_names": FEATURE_NAMES,
            "metrics": metrics,
        }
        self.save()
        return self.meta

    def save(self):
        if self.mlp:
            self.mlp.save(self.model_path)
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(self.meta, f, ensure_ascii=False, indent=2)

    def load(self) -> bool:
        if not os.path.exists(self.model_path):
            return False
        self.mlp = NumPyMLP.load(self.model_path)
        if os.path.exists(self.meta_path):
            with open(self.meta_path, "r", encoding="utf-8") as f:
                self.meta = json.load(f)
        return True

    def predict_proba_map(self, stocks, sector_data=None, market_ctx=None):
        if self.mlp is None and not self.load():
            return {}
        codes, X = self.build_matrix(stocks, sector_data, market_ctx)
        if not codes:
            return {}
        proba = self.mlp.predict_proba(X)
        return {c: float(p) for c, p in zip(codes, proba)}

    def apply_to_picks(self, picks, dl_scores, min_dl=0.5, boost=15.0):
        out = []
        for p in picks:
            code = p.get("code")
            ds = dl_scores.get(code, 0.0)
            p = dict(p)
            p["dl_score"] = round(ds, 4)
            if ds < min_dl:
                continue
            p["strategy_score"] = int(p.get("strategy_score", 0) + ds * boost)
            p["final_score"] = p["strategy_score"]
            out.append(p)
        out.sort(key=lambda x: x.get("strategy_score", 0), reverse=True)
        return out
