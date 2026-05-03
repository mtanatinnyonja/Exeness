"""
Grid-search optimizer for Exeness XAUUSDm technical parameters.

Usage:
    python optimizer.py XAUUSDm 30
"""

from __future__ import annotations

import json
import itertools
import multiprocessing as mp
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from tqdm import tqdm

from backtest import SimpleBacktester
from mt5_bridge import build_broker
import signal_engine

OPT_PATH = Path("data/optimized_params.json")


def _iter_param_combinations(param_grid: Dict[str, List]) -> List[Dict]:
    keys = list(param_grid.keys())
    values = [param_grid[k] for k in keys]
    combos = []
    for row in itertools.product(*values):
        combos.append({k: v for k, v in zip(keys, row)})
    return combos


def _evaluate_combo(args: Tuple[str, int, Dict]) -> Dict:
    instrument, days, params = args

    # Apply indicator params only in this worker process.
    signal_engine.apply_optimized_params(params)
    score_threshold = int(params.get("score_threshold", 3))

    broker = build_broker()
    bt = SimpleBacktester(broker, instrument)
    stats = bt.run_backtest(days=days, score_threshold=score_threshold)

    result = {
        "instrument": instrument,
        "days": int(days),
        "RSI_PERIOD": int(params.get("RSI_PERIOD", signal_engine.RSI_PERIOD)),
        "MA_FAST": int(params.get("MA_FAST", signal_engine.MA_FAST)),
        "MA_SLOW": int(params.get("MA_SLOW", signal_engine.MA_SLOW)),
        "BB_PERIOD": int(params.get("BB_PERIOD", signal_engine.BB_PERIOD)),
        "ATR_PERIOD": int(params.get("ATR_PERIOD", signal_engine.ATR_PERIOD)),
        "score_threshold": score_threshold,
        "total_trades": int(stats.get("total_trades", 0) or 0),
        "closed_trades": int(stats.get("closed_trades", 0) or 0),
        "win_rate": float(stats.get("win_rate", 0.0) or 0.0),
        "total_pnl": float(stats.get("total_pnl", 0.0) or 0.0),
        "max_drawdown": float(stats.get("max_drawdown", 0.0) or 0.0),
        "sharpe_ratio": float(stats.get("sharpe_ratio", 0.0) or 0.0),
        "profit_factor": float(stats.get("profit_factor", 0.0) or 0.0),
        "final_balance": float(stats.get("final_balance", 0.0) or 0.0),
    }
    return result


def grid_search(instrument: str, days: int, param_grid: Dict[str, List]) -> List[Dict]:
    combos = _iter_param_combinations(param_grid)
    if not combos:
        return []

    workers = min(4, max(1, mp.cpu_count() // 2), len(combos))
    jobs = [(instrument, days, combo) for combo in combos]

    results: List[Dict] = []
    with mp.Pool(processes=workers) as pool:
        for row in tqdm(pool.imap_unordered(_evaluate_combo, jobs), total=len(jobs), desc="Grid search"):
            # Ignore statistically weak configurations (<10 trades)
            if int(row.get("closed_trades", 0) or 0) < 10:
                continue
            results.append(row)

    results.sort(key=lambda r: float(r.get("sharpe_ratio", 0.0) or 0.0), reverse=True)
    return results


def save_best_params(best_result: Dict) -> bool:
    """
    Save best params only if Sharpe ratio improves previous saved result.
    Returns True if file updated, else False.
    """
    if not best_result:
        return False

    new_sharpe = float(best_result.get("sharpe_ratio", 0.0) or 0.0)
    old_payload = {}
    old_sharpe = float("-inf")

    if OPT_PATH.exists():
        try:
            old_payload = json.loads(OPT_PATH.read_text(encoding="utf-8"))
            old_sharpe = float(old_payload.get("best", {}).get("sharpe_ratio", float("-inf")))
        except Exception:
            old_sharpe = float("-inf")

    if new_sharpe <= old_sharpe:
        return False

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "best": best_result,
        "params": {
            "RSI_PERIOD": int(best_result.get("RSI_PERIOD", signal_engine.RSI_PERIOD)),
            "MA_FAST": int(best_result.get("MA_FAST", signal_engine.MA_FAST)),
            "MA_SLOW": int(best_result.get("MA_SLOW", signal_engine.MA_SLOW)),
            "BB_PERIOD": int(best_result.get("BB_PERIOD", signal_engine.BB_PERIOD)),
            "ATR_PERIOD": int(best_result.get("ATR_PERIOD", signal_engine.ATR_PERIOD)),
            "score_threshold": int(best_result.get("score_threshold", 3)),
        },
    }

    OPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def _default_grid() -> Dict[str, List]:
    return {
        "RSI_PERIOD": [10, 14, 21],
        "MA_FAST": [9, 12, 20],
        "MA_SLOW": [30, 50],
        "BB_PERIOD": [20],
        "ATR_PERIOD": [14],
        "score_threshold": [2, 3, 4],
    }


def main() -> int:
    instrument = sys.argv[1] if len(sys.argv) > 1 else "XAUUSDm"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 30

    grid = _default_grid()
    print(f"[OPT] Start grid search: instrument={instrument} days={days} combos={len(_iter_param_combinations(grid))}")

    results = grid_search(instrument, days, grid)
    if not results:
        print("[OPT] No significant result (all combos filtered by <10 trades).")
        return 0

    best = results[0]
    updated = save_best_params(best)

    print("\n[OPT] Top 5 by Sharpe:")
    for i, row in enumerate(results[:5], 1):
        print(
            f"#{i} sharpe={row['sharpe_ratio']:.3f} pnl={row['total_pnl']:.2f} "
            f"trades={row['closed_trades']} rsi={row['RSI_PERIOD']} ma_fast={row['MA_FAST']} "
            f"ma_slow={row['MA_SLOW']} threshold={row['score_threshold']}"
        )

    if updated:
        print(f"[OPT] optimized params saved to {OPT_PATH}")
    else:
        print("[OPT] existing optimized params kept (new Sharpe not better)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
