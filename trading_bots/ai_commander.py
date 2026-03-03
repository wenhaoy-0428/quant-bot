"""AI Commander: produces slow, high-level guidance for the soldier loop.

Runs independently from the fast per-candle execution. It periodically calls
DeepSeek to infer macro bias and risk posture, then writes a compact guidance
file the soldier reads synchronously.
"""

import json
import os
import time
import traceback
from datetime import datetime
from pathlib import Path

from trading_bots.guidance import save_guidance
import core.services.market_data_service as mds_mod
import core.services.ai_service as ais_mod


LOG_PATH = Path(os.getenv("COMMANDER_LOG_PATH", "logs/commander.log"))
MAX_LOG_BYTES = 512_000
LOG_BACKUPS = 3


def rotate_log(path: Path, max_bytes: int = MAX_LOG_BYTES, backups: int = LOG_BACKUPS):
    if not path.exists() or path.stat().st_size < max_bytes:
        return
    for idx in range(backups - 1, 0, -1):
        older = path.with_suffix(path.suffix + f".{idx}")
        newer = path.with_suffix(path.suffix + f".{idx + 1}")
        if older.exists():
            older.rename(newer)
    rotated = path.with_suffix(path.suffix + ".1")
    path.rename(rotated)


def log(msg: str):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    rotate_log(LOG_PATH)
    timestamp = datetime.utcnow().isoformat() + "Z"
    line = f"[{timestamp}] {msg}"
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def to_guidance(signal_data):
    """Translate DeepSeek response into commander guidance tokens."""
    signal = signal_data.get("signal", "HOLD")
    risk_assessment = str(signal_data.get("risk_assessment", "中风险"))

    if signal == "BUY":
        bias = "BULLISH"
    elif signal == "SELL":
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    if "高风险" in risk_assessment:
        vol_mode = "DEFENSIVE"
    elif "低风险" in risk_assessment:
        vol_mode = "STANDARD"
    else:
        vol_mode = "STANDARD"

    return {
        "bias": bias,
        "volatility_mode": vol_mode,
        "reason": signal_data.get("reason", "AI commander refresh"),
        "last_updated": datetime.utcnow().isoformat() + "Z",
    }


def update_guidance_once():
    try:
        # Use module-level access to get the initialized service instance
        mds = mds_mod.market_data_service
        ais = ais_mod.ai_service
        
        if not mds or not ais:
            log("Commander: 服务未初始化")
            return

        price_data = mds.get_enriched_ohlcv()
        if not price_data:
            log("Commander: 获取行情失败，保持当前指导")
            return

        signal_data = ais.analyze(price_data)
        guidance = to_guidance(signal_data)
        save_guidance(guidance)
        log(f"Commander 更新: bias={guidance['bias']} vol={guidance['volatility_mode']}")
    except Exception as exc:
        log(f"Commander 异常: {exc}")
        traceback.print_exc()


def suggest_parameters_from_backtest(metrics: dict):
    """Use DeepSeek to suggest parameter tweaks based on backtest metrics."""
    # Use module-level access
    ais = ais_mod.ai_service
    if not ais:
        return "{}"

    prompt = (
        "You are a trading risk assistant. Given backtest metrics, propose 3 concise parameter tweaks "
        "to improve risk-adjusted returns. Respond in compact JSON with keys: tweaks (array of strings), "
        "risk_note (string), and confidence (0-1). Keep answers short."
        f"\nMetrics: {json.dumps(metrics)}"
    )
    try:
        resp = ais._client.chat.completions.create(
            model=ais._model,
            messages=[{"role": "system", "content": "You are a concise quant assistant."}, {"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=240,
        )
        content = resp.choices[0].message.content if resp.choices else "{}"
        log(f"Commander 参数建议生成成功")
        return content
    except Exception as exc:
        log(f"Commander 参数建议失败: {exc}")
        return json.dumps({
            "tweaks": ["Reduce leverage by 1-2x", "Tighten stop loss by 5-10%", "Lower base risk per trade by 25% until win-rate improves"],
            "risk_note": "Fallback heuristic used because AI call failed.",
            "confidence": 0.2,
        })


def main():
    try:
        from core.services import (
            exchange_service,
            sentiment_service,
            signal_service,
        )
        from core.config import config
        from core.models.performance_tracker import tracker

        log("AI Commander 初始化服务中...")
        ex = exchange_service.initialize()
        sen = sentiment_service.initialize()
        sig = signal_service.initialize(tracker)
        mds_mod.initialize(ex)
        ais_mod.initialize(config, sig, sen)
        log("✅ 服务初始化完成")
    except Exception as e:
        log(f"❌ 服务初始化失败: {e}")
        # Continue mostly to allow loop to start and maybe retry? 
        # But if init failed, update_guidance_once will fail too.
        # We'll just let it run and log errors.
        pass

    interval_min = int(os.getenv("COMMANDER_INTERVAL_MINUTES", "60"))
    log(f"AI Commander 启动，刷新间隔: {interval_min} 分钟")
    while True:
        update_guidance_once()
        time.sleep(max(60, interval_min * 60))


if __name__ == "__main__":
    main()
