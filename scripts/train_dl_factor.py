#!/usr/bin/env python3
"""训练 DL 因子 MLP 模型

用法:
  python scripts/build_dl_dataset.py --pool-top 500
  python scripts/train_dl_factor.py
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from dl_factor_model import DLFactorSelector


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=os.path.join(BASE, "data", "ml_models", "dl_train_dataset.npz"))
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--build", action="store_true", help="先构建数据集再训练")
    args = parser.parse_args()

    if args.build:
        import subprocess
        subprocess.check_call([sys.executable, os.path.join(BASE, "scripts", "build_dl_dataset.py"), "--pool-top", "500"])

    if not os.path.exists(args.dataset):
        print("数据集不存在，运行: python scripts/build_dl_dataset.py")
        sys.exit(1)

    data = np.load(args.dataset)
    X, y = data["X"], data["y"]
    print(f"加载样本: {len(y)} | 正类 {y.mean():.1%}")

    sel = DLFactorSelector()
    meta = sel.train(X, y, epochs=args.epochs)
    print(f"训练完成: train_acc={meta['metrics']['train_acc']:.1%} val_acc={meta['metrics']['val_acc']:.1%}")
    print(f"模型: {sel.model_path}")


if __name__ == "__main__":
    main()
