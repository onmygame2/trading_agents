"""
ML选股分类器 - 纯 NumPy 实现，零外部依赖

两种模式:
  1. FactorRanker: 基于历史IC(信息系数)的因子加权排名系统
  2. LogisticRegression: 纯NumPy实现的逻辑回归分类器

选股标签定义:
  - 未来5日收益率是否跑赢等权重基准 → 二分类 (0/1)
  - 未来5日收益率分位数 → 排序回归

Usage:
    from ml_stock_selector import MLStockSelector

    selector = MLStockSelector()

    # 训练: 传入历史因子数据 (list of dicts)
    X, y = selector._prepare_training_data(historical_factors, lookback_days=5)
    selector.train(X, y)

    # 预测: 传入今日因子数据
    predictions = selector.predict(today_factors_df)

    # 推荐股票 (top_N)
    top_stocks = selector.recommend(today_factors_df, top_n=10)
"""

import json
import os
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class LogisticRegression:
    """纯 NumPy 实现的逻辑回归分类器.

    支持 L2 正则化, SGD 训练, predict_proba 概率输出.

    Features:
        - 标准化输入 (内部自动处理)
        - L2 正则化防止过拟合
        - Mini-batch SGD
        - 保存/加载模型参数
    """

    def __init__(self, lr: float = 0.01, l2_reg: float = 0.01, n_epochs: int = 100, batch_size: int = 64):
        self.lr = lr
        self.l2_reg = l2_reg
        self.n_epochs = n_epochs
        self.batch_size = batch_size
        self.weights = None
        self.bias = 0.0
        self.mean = None
        self.std = None

    def _standardize(self, X: np.ndarray, fit: bool = False) -> np.ndarray:
        if fit:
            self.mean = np.mean(X, axis=0)
            self.std = np.std(X, axis=0)
            self.std[self.std < 1e-8] = 1.0
        return (X - self.mean) / self.std

    @staticmethod
    def _sigmoid(z: np.ndarray) -> np.ndarray:
        z = np.clip(z, -500, 500)
        return 1.0 / (1.0 + np.exp(-z))

    def fit(self, X: np.ndarray, y: np.ndarray) -> 'LogisticRegression':
        X = self._standardize(X, fit=True)
        n_samples, n_features = X.shape
        self.weights = np.zeros(n_features)
        self.bias = 0.0

        for epoch in range(self.n_epochs):
            # Shuffle
            indices = np.random.permutation(n_samples)
            X_shuffled = X[indices]
            y_shuffled = y[indices]

            for start in range(0, n_samples, self.batch_size):
                end = min(start + self.batch_size, n_samples)
                X_batch = X_shuffled[start:end]
                y_batch = y_shuffled[start:end]

                # Forward
                z = X_batch @ self.weights + self.bias
                preds = self._sigmoid(z)

                # Gradient
                error = preds - y_batch
                dw = (X_batch.T @ error) / len(y_batch) + self.l2_reg * self.weights
                db = np.mean(error)

                # Update
                self.weights -= self.lr * dw
                self.bias -= self.lr * db

        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X = self._standardize(X, fit=False)
        z = X @ self.weights + self.bias
        return self._sigmoid(z)

    def predict(self, X: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        return (self.predict_proba(X) >= threshold).astype(int)

    def feature_importance(self) -> np.ndarray:
        if self.weights is None:
            return np.array([])
        return np.abs(self.weights)

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
        np.savez(path, weights=self.weights, bias=np.array([self.bias]),
                 mean=self.mean, std=self.std)

    def load(self, path: str) -> 'LogisticRegression':
        data = np.load(path)
        self.weights = data['weights']
        self.bias = float(data['bias'][0])
        self.mean = data['mean']
        self.std = data['std']
        return self


class FactorRanker:
    """基于历史 IC (Information Coefficient) 的因子加权排名.

    核心思路:
      1. 计算每个因子与未来收益的相关性 (IC)
      2. 用 IC 作为因子权重进行加权打分
      3. 按综合得分排名选股

    优点: 简单、可解释、不需要训练过程.
    """

    def __init__(self):
        self.factor_names: List[str] = []
        self.ic_weights: Dict[str, float] = {}
        self.factor_directions: Dict[str, int] = {}  # 1=正向, -1=反向

    def compute_ic(self, factor_matrix: np.ndarray, future_returns: np.ndarray) -> Dict[str, float]:
        """计算每个因子的 IC (与未来收益的Spearman相关系数).

        Args:
            factor_matrix: (n_stocks, n_factors) 每日因子矩阵
            future_returns: (n_stocks,) 未来收益率

        Returns:
            Dict of factor_name -> ic_value
        """
        ic_dict = {}
        for i, fname in enumerate(self.factor_names):
            factor_vals = factor_matrix[:, i]
            # Spearman: rank correlation
            rank_factor = self._rank(factor_vals)
            rank_return = self._rank(future_returns)
            ic = np.corrcoef(rank_factor, rank_return)[0, 1]
            if np.isnan(ic):
                ic = 0.0
            ic_dict[fname] = ic
        return ic_dict

    @staticmethod
    def _rank(arr: np.ndarray) -> np.ndarray:
        """Compute rank of each element, handling ties."""
        sorter = np.argsort(arr)
        ranks = np.empty_like(sorter, dtype=float)
        ranks[sorter] = np.arange(1, len(arr) + 1)
        # Handle ties: average rank
        unique_vals, counts = np.unique(arr, return_counts=True)
        for val, count in zip(unique_vals, counts):
            mask = arr == val
            avg_rank = np.mean(ranks[mask])
            ranks[mask] = avg_rank
        return ranks

    def train_ic_weights(self, historical_data: List[Dict[str, Any]]) -> Dict[str, float]:
        """从历史数据中计算因子 IC 均值作为权重.

        Args:
            historical_data: List of dicts with keys:
                - 'factors': Dict of factor_name -> value for each stock
                - 'future_return': float, future 5-day return
                - 'codes': List of stock codes

        Returns:
            Dict of factor_name -> ic_weight
        """
        if not historical_data:
            return {}

        # Collect all factor names
        all_factors = set()
        for entry in historical_data:
            all_factors.update(entry.get('factors', {}).keys())
        self.factor_names = sorted(all_factors)

        # For each day, compute IC
        ic_sum = {f: 0.0 for f in self.factor_names}
        ic_count = {f: 0 for f in self.factor_names}

        for day_data in historical_data:
            codes = day_data.get('codes', [])
            factors = day_data.get('factors', {})
            future_ret = day_data.get('future_return', {})

            if not codes or not factors:
                continue

            # Build factor matrix
            factor_matrix = []
            returns = []
            for code in codes:
                row = []
                for f in self.factor_names:
                    row.append(factors.get(code, {}).get(f, 0.0))
                factor_matrix.append(row)
                returns.append(future_ret.get(code, 0.0))

            if len(returns) < 20:
                continue

            factor_matrix = np.array(factor_matrix)
            future_returns = np.array(returns)

            day_ic = self.compute_ic(factor_matrix, future_returns)
            for f in self.factor_names:
                ic = day_ic.get(f, 0.0)
                if not np.isnan(ic):
                    ic_sum[f] += ic
                    ic_count[f] += 1

        # Average IC as weight
        for f in self.factor_names:
            if ic_count[f] > 0:
                avg_ic = ic_sum[f] / ic_count[f]
                self.ic_weights[f] = abs(avg_ic)
                self.factor_directions[f] = 1 if avg_ic > 0 else -1
            else:
                self.ic_weights[f] = 0.0
                self.factor_directions[f] = 1

        return dict(self.ic_weights)

    def score_stocks(self, factors_dict: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
        """对股票列表进行因子打分排名.

        Args:
            factors_dict: {code: {factor_name: value}}

        Returns:
            List of {code, score, factor_scores} sorted by score descending.
        """
        if not self.ic_weights:
            # Fallback: equal weight on all factors
            all_factors = set()
            for fdict in factors_dict.values():
                all_factors.update(fdict.keys())
            if all_factors:
                weight = 1.0 / len(all_factors)
                self.ic_weights = {f: weight for f in all_factors}
                self.factor_directions = {f: 1 for f in all_factors}
                self.factor_names = sorted(all_factors)

        results = []
        for code, factors in factors_dict.items():
            factor_scores = {}
            total_score = 0.0
            total_weight = 0.0
            for f in self.factor_names:
                val = factors.get(f, 0.0)
                w = self.ic_weights.get(f, 0.0)
                direction = self.factor_directions.get(f, 1)
                # Normalize factor value to [-1, 1] range using tanh
                normalized = np.tanh(val)
                score = w * normalized * direction
                factor_scores[f] = round(float(score), 4)
                total_score += score
                total_weight += w
            if total_weight > 0:
                total_score /= total_weight
            results.append({
                'code': code,
                'score': round(float(total_score), 4),
                'factor_scores': factor_scores,
            })

        results.sort(key=lambda x: x['score'], reverse=True)
        return results


class MLStockSelector:
    """ML选股主入口.

    组合使用 FactorRanker (IC加权排名) + LogisticRegression (分类器).
    最终输出: 每日推荐股票列表 + 置信度.

    训练流程:
      1. 每天计算所有股票的因子
      2. 记录未来5日收益
      3. 定期重新训练模型

    预测流程:
      1. 读取今日因子
      2. 运行分类器 + 因子排名
      3. 融合两个信号
      4. 输出推荐列表
    """

    def __init__(self, model_dir: str = None):
        self.model_dir = model_dir or './data/ml_models'
        os.makedirs(self.model_dir, exist_ok=True)

        self.classifier = LogisticRegression(lr=0.05, l2_reg=0.001, n_epochs=200, batch_size=128)
        self.ranker = FactorRanker()

        # 因子列名
        self.factor_columns: List[str] = []
        # 训练元数据
        self.train_date: str = ''
        self.train_samples: int = 0

    def get_factor_columns(self) -> List[str]:
        """获取因子维度列名 (与 factor_engine_v2 对齐)."""
        return [
            'trend', 'fundamental', 'valuation', 'sector', 'capital', 'momentum',
            'rsi', 'macd', 'vol_ratio', 'change_pct', 'pe', 'pb', 'roe',
            'north_flow', 'turnover', 'market_cap',
        ]

    def prepare_training_data(
        self,
        historical_factors: Dict[str, Dict[str, Dict[str, float]]],
        historical_prices: Dict[str, pd.DataFrame],
        label_window: int = 5,
        min_return: float = 0.0,
    ) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        """准备训练数据.

        Args:
            historical_factors: {date: {code: {factor: value}}}
            historical_prices: {code: DataFrame with date, close columns}
            label_window: 未来N日收益率作为标签
            min_return: 正类阈值 (收益 > min_return 为正类)

        Returns:
            (X, y, dates) — features, labels, corresponding dates
        """
        import pandas as pd

        # Get factor columns
        if not self.factor_columns:
            self.factor_columns = self.get_factor_columns()

        X_list = []
        y_list = []
        date_list = []

        sorted_dates = sorted(historical_factors.keys())

        for date_str in sorted_dates:
            day_factors = historical_factors.get(date_str, {})
            if not day_factors:
                continue

            # Calculate future return for each stock
            try:
                current_date = pd.Timestamp(date_str)
            except Exception:
                continue

            for code, factors in day_factors.items():
                # Get future price
                if code not in historical_prices:
                    continue
                price_df = historical_prices[code]
                price_df = price_df.copy()
                price_df['date'] = pd.to_datetime(price_df['date'])

                future_prices = price_df[price_df['date'] > current_date].head(label_window)
                if future_prices.empty:
                    continue

                current_price = price_df[price_df['date'] == current_date]['close']
                if current_price.empty:
                    current_price = price_df.sort_values('date').tail(1)['close']

                future_price = future_prices.tail(1)['close'].values[0]
                current_price_val = current_price.values[0] if len(current_price.values) > 0 else 0

                if current_price_val <= 0:
                    continue

                future_return = (future_price - current_price_val) / current_price_val

                # Label: 1 if outperforms threshold
                label = 1 if future_return > min_return else 0

                # Build feature vector
                feature_vec = []
                for col in self.factor_columns:
                    feature_vec.append(factors.get(col, 0.0))

                X_list.append(feature_vec)
                y_list.append(label)
                date_list.append(date_str)

        if not X_list:
            return np.array([]), np.array([]), []

        X = np.array(X_list, dtype=np.float64)
        y = np.array(y_list, dtype=np.float64)

        # Clean NaN/inf
        X = np.nan_to_num(X, nan=0.0, posinf=10.0, neginf=-10.0)

        return X, y, date_list

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        dates: List[str] = None,
    ) -> Dict[str, Any]:
        """训练选股模型.

        Args:
            X: Feature matrix (n_samples, n_features)
            y: Labels (n_samples,)
            dates: Optional date list for logging

        Returns:
            Training summary dict.
        """
        if len(X) == 0 or len(X.shape) < 2:
            return {'status': 'error', 'message': 'No training data'}

        n_samples, n_features = X.shape

        # Split train/val (80/20)
        split = int(n_samples * 0.8)
        indices = np.random.permutation(n_samples)
        train_idx = indices[:split]
        val_idx = indices[split:]

        X_train, y_train = X[train_idx], y[train_idx]
        X_val, y_val = X[val_idx], y[val_idx]

        # Train classifier
        self.classifier.fit(X_train, y_train)

        # Evaluate
        train_proba = self.classifier.predict_proba(X_train)
        train_pred = (train_proba >= 0.5).astype(int)
        train_acc = np.mean(train_pred == y_train)

        val_proba = self.classifier.predict_proba(X_val)
        val_pred = (val_proba >= 0.5).astype(int)
        val_acc = np.mean(val_pred == y_val)

        # AUC approximation
        val_auc = self._compute_auc(val_proba, y_val)

        # Feature importance
        importance = self.classifier.feature_importance()
        feat_importance = {}
        for i, col in enumerate(self.factor_columns):
            feat_importance[col] = round(float(importance[i]), 4)

        # Save model
        model_path = os.path.join(self.model_dir, 'classifier.npz')
        self.classifier.save(model_path)

        # Save metadata
        meta = {
            'train_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'train_samples': int(n_samples),
            'n_features': int(n_features),
            'factor_columns': self.factor_columns,
            'train_accuracy': round(float(train_acc), 4),
            'val_accuracy': round(float(val_acc), 4),
            'val_auc': round(float(val_auc), 4),
            'feature_importance': feat_importance,
        }
        meta_path = os.path.join(self.model_dir, 'model_meta.json')
        with open(meta_path, 'w') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        logger.info(f"Model trained: {n_samples} samples, val_acc={val_acc:.4f}, val_auc={val_auc:.4f}")

        return {
            'status': 'success',
            'train_accuracy': round(float(train_acc), 4),
            'val_accuracy': round(float(val_acc), 4),
            'val_auc': round(float(val_auc), 4),
            'train_samples': int(n_samples),
            'feature_importance': feat_importance,
            'model_path': model_path,
        }

    def predict(self, factors_dict: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
        """对今日因子数据进行预测.

        Args:
            factors_dict: {code: {factor_name: value}}

        Returns:
            List of {code, ml_score, rank_score, combined_score, signal} sorted by combined_score.
        """
        if not self.factor_columns:
            self.factor_columns = self.get_factor_columns()

        codes = sorted(factors_dict.keys())
        if not codes:
            return []

        # Build feature matrix
        X = []
        for code in codes:
            feature_vec = []
            for col in self.factor_columns:
                feature_vec.append(factors_dict[code].get(col, 0.0))
            X.append(feature_vec)
        X = np.array(X, dtype=np.float64)
        X = np.nan_to_num(X, nan=0.0, posinf=10.0, neginf=-10.0)

        # ML prediction
        ml_scores = np.zeros(len(codes))
        if self.classifier.weights is not None:
            try:
                ml_scores = self.classifier.predict_proba(X)
            except Exception as e:
                logger.warning(f"ML prediction failed: {e}")

        # Factor ranking score
        rank_results = self.ranker.score_stocks(factors_dict)
        rank_score_dict = {r['code']: r['score'] for r in rank_results}

        # Combine: 60% ML + 40% Factor Rank
        results = []
        for i, code in enumerate(codes):
            ml_score = float(ml_scores[i])
            rank_score = rank_score_dict.get(code, 0.0)
            # Normalize rank score to [0, 1]
            rank_normalized = (rank_score + 1) / 2  # from [-1,1] to [0,1]
            combined = 0.6 * ml_score + 0.4 * rank_normalized

            signal = 'strong_buy' if combined > 0.7 else \
                     'buy' if combined > 0.55 else \
                     'hold' if combined > 0.45 else \
                     'sell' if combined > 0.3 else \
                     'strong_sell'

            results.append({
                'code': code,
                'ml_score': round(ml_score, 4),
                'rank_score': round(rank_score, 4),
                'combined_score': round(combined, 4),
                'signal': signal,
            })

        results.sort(key=lambda x: x['combined_score'], reverse=True)
        return results

    def recommend(self, factors_dict: Dict[str, Dict[str, float]], top_n: int = 10) -> List[Dict[str, Any]]:
        """推荐 top_N 股票.

        Args:
            factors_dict: {code: {factor_name: value}}
            top_n: Number of top stocks to recommend.

        Returns:
            List of top stock recommendations.
        """
        predictions = self.predict(factors_dict)
        return predictions[:top_n]

    def load_model(self) -> bool:
        """加载已保存的模型."""
        model_path = os.path.join(self.model_dir, 'classifier.npz')
        meta_path = os.path.join(self.model_dir, 'model_meta.json')

        if os.path.exists(model_path):
            try:
                self.classifier.load(model_path)
            except Exception as e:
                logger.error(f"Failed to load classifier: {e}")
                return False

        if os.path.exists(meta_path):
            with open(meta_path, 'r') as f:
                meta = json.load(f)
            self.factor_columns = meta.get('factor_columns', [])
            self.train_date = meta.get('train_date', '')
            self.train_samples = meta.get('train_samples', 0)

        return len(self.factor_columns) > 0

    def get_model_info(self) -> Dict[str, Any]:
        """获取模型信息."""
        meta_path = os.path.join(self.model_dir, 'model_meta.json')
        if os.path.exists(meta_path):
            with open(meta_path, 'r') as f:
                return json.load(f)
        return {'status': 'no_model', 'message': 'No trained model found'}

    @staticmethod
    def _compute_auc(probas: np.ndarray, labels: np.ndarray) -> float:
        """Compute AUC (Area Under ROC Curve)."""
        if len(probas) < 2:
            return 0.5

        # Sort by probability descending
        sorted_indices = np.argsort(-probas)
        sorted_labels = labels[sorted_indices]

        n_pos = np.sum(labels == 1)
        n_neg = np.sum(labels == 0)

        if n_pos == 0 or n_neg == 0:
            return 0.5

        # Trapezoidal AUC
        tp = 0
        fp = 0
        auc = 0.0
        prev_fpr = 0.0
        prev_tpr = 0.0

        for i in range(len(sorted_labels)):
            if sorted_labels[i] == 1:
                tp += 1
            else:
                fp += 1
            fpr = fp / n_neg
            tpr = tp / n_pos
            auc += (fpr - prev_fpr) * (tpr + prev_tpr) / 2
            prev_fpr = fpr
            prev_tpr = tpr

        return float(auc)
