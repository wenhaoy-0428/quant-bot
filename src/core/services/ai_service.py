"""AI service.

Wraps all DeepSeek / OpenAI LLM interactions.  Replaces the following
functions from ``trading_bots/signals.py``:

  analyze_with_deepseek_trend_king_with_retry  → AIService.analyze()
  analyze_with_deepseek_trend_king             → AIService._analyze_once()
  build_trend_king_prompt                      → AIService._build_prompt()
  generate_technical_analysis_text            → AIService._build_analysis_text()
  safe_json_parse                              → AIService._safe_json_parse()
  create_fallback_signal                       → AIService._create_fallback()

Used by:
  trading_bots/ai_commander.py  (runs as a separate background process)

Not used by the main bot loop — that path uses SignalService.generate()
which is pure technical analysis + guidance filter, no AI calls.
"""

import json
import re
import time
import traceback
from typing import Optional

import pandas as pd
from openai import OpenAI

from core.config import Config, config as _default_config
from core.services.sentiment_service import SentimentService, sentiment_service as _default_sentiment
from core.services.signal_service import SignalService, signal_service as _default_signals
from core.utils.indicators import calculate_volatility


class AIService:
    """Calls DeepSeek to generate a high-confidence trading signal.

    The commander process (``ai_commander.py``) calls ``analyze(price_data)``
    once per hour.  The result is translated into guidance and written to disk.

    Args:
        cfg:              Configuration object (API key, model name, etc.).
        signal_service:   Provides ``generate_technical_signal()`` and
                          ``calculate_stop_loss()`` so we don't duplicate logic.
        sentiment_service: Fetches live sentiment data for the prompt.
    """

    def __init__(
        self,
        cfg: Config,
        signal_svc: SignalService,
        sentiment_svc: SentimentService,
    ) -> None:
        self._client = OpenAI(api_key=cfg.ai_api_key, base_url=cfg.ai_base_url)
        self._model = cfg.model_name
        self._timeframe = cfg.timeframe
        self._signals = signal_svc
        self._sentiment = sentiment_svc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, price_data: dict, max_retries: int = 2) -> dict:
        """Return a DeepSeek-enhanced signal, with up to ``max_retries`` attempts.

        Falls back to the pure technical signal if all attempts fail.
        """
        for attempt in range(max_retries):
            try:
                result = self._analyze_once(price_data)
                if result and not result.get("is_fallback", False):
                    return result
                print(f"第{attempt + 1}次尝试失败，进行重试...")
                time.sleep(1)
            except Exception as exc:
                print(f"第{attempt + 1}次尝试异常: {exc}")
                if attempt == max_retries - 1:
                    return self._fallback(price_data)
                time.sleep(1)

        return self._fallback(price_data)

    # ------------------------------------------------------------------
    # Private: single attempt
    # ------------------------------------------------------------------

    def _analyze_once(self, price_data: dict) -> dict:
        """One DeepSeek call using the trend-king prompt."""
        technical = self._signals.generate_technical_signal(price_data)
        prompt = self._build_prompt(price_data, technical)

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是指挥官，必须执行对称的BUY/SELL 8条规则，禁止逆大趋势、禁止越权修改风控参数。"
                            "小概率机会宁可HOLD，遇到资金费率极端、RSI越界、重大事件窗口或多时间框架不对齐时一律HOLD。"
                            "输出必须为JSON，字段完整且无额外文本。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                temperature=0.1,
            )

            raw = response.choices[0].message.content
            print(f"🎯 DeepSeek趋势为王分析回复: {raw}")

            start = raw.find("{")
            end = raw.rfind("}") + 1
            signal_data = self._safe_json_parse(raw[start:end]) if start != -1 and end != 0 else technical

            if not all(f in signal_data for f in ("signal", "reason", "confidence")):
                signal_data = technical

            # Preserve technical metadata
            signal_data["trend_score"] = technical["trend_score"]
            signal_data["primary_trend"] = technical["primary_trend"]
            signal_data["structure_signals"] = technical["structure_signals"]
            signal_data["structure_optimized"] = technical["structure_optimized"]

            # Enforce trend-strength gate
            trend_score = technical.get("trend_score", 0)
            tech_signal_type = technical.get("signal", "HOLD")
            if trend_score < 8:
                if signal_data.get("signal") != "HOLD":
                    print(f"🛑 强制HOLD：趋势强度{trend_score}/10 < 8，禁止AI覆盖技术信号")
                    signal_data["signal"] = "HOLD"
                    signal_data["confidence"] = "LOW"
                    signal_data["reason"] = (
                        f"趋势强度{trend_score}/10 < 8，严格执行趋势强度过滤"
                        f"（技术信号：{tech_signal_type}，AI建议被拒绝）"
                    )
            elif tech_signal_type == "HOLD" and trend_score >= 8:
                print(f"✅ 趋势强度{trend_score}/10 ≥ 8，允许AI分析覆盖技术信号HOLD")

            if "risk_assessment" not in signal_data:
                signal_data["risk_assessment"] = technical["risk_assessment"]

            stop_loss, take_profit = self._signals.calculate_stop_loss(signal_data, price_data)
            signal_data["stop_loss"] = stop_loss
            signal_data["take_profit"] = take_profit
            signal_data["timestamp"] = price_data["timestamp"]

            return signal_data

        except Exception as exc:
            print(f"❌ DeepSeek趋势为王分析失败: {exc}")
            traceback.print_exc()
            return self._fallback(price_data, technical)

    def _fallback(self, price_data: dict, technical: Optional[dict] = None) -> dict:
        """Return the technical signal (with stop-loss) as a fallback."""
        sig = technical or self._signals.generate_technical_signal(price_data)
        stop_loss, take_profit = self._signals.calculate_stop_loss(sig, price_data)
        sig["stop_loss"] = stop_loss
        sig["take_profit"] = take_profit
        sig["is_fallback"] = True
        return sig

    # ------------------------------------------------------------------
    # Private: prompt builders
    # ------------------------------------------------------------------

    def _build_prompt(self, price_data: dict, technical: dict) -> str:
        """Build the 8-rule trend-king prompt for the commander."""
        sentiment_data = self._sentiment.get_indicators()
        if sentiment_data:
            sign = "+" if sentiment_data["net_sentiment"] >= 0 else ""
            sentiment_text = (
                f"\n    【市场情绪】\n"
                f"    - 乐观比例: {sentiment_data['positive_ratio']:.1%}\n"
                f"    - 悲观比例: {sentiment_data['negative_ratio']:.1%}\n"
                f"    - 情绪净值: {sign}{sentiment_data['net_sentiment']:.3f}\n"
                f"    - 数据时间: {sentiment_data['data_time']} (延迟: {sentiment_data['data_delay_minutes']}分钟)\n"
            )
        else:
            sentiment_text = (
                "\n    【市场情绪】\n"
                "    - 数据暂不可用（API中断或配置问题，已自动降级为纯技术分析模式）\n"
            )

        bb_position = price_data["technical_data"].get("bb_position", 0)
        trend_score = technical["trend_score"]
        if trend_score >= 8:
            if (technical["primary_trend"] == "强势上涨" and bb_position < 0.1) or (
                technical["primary_trend"] == "强势下跌" and bb_position > 0.9
            ):
                structure_relation = "趋势加速"
            else:
                structure_relation = "结构确认"
        else:
            structure_relation = "结构确认"

        structure_str = (
            ", ".join(technical["structure_signals"]) if technical["structure_signals"] else "无"
        )

        return f"""
    你是"指挥官"，负责BTC/USDT合约信号，必须执行对称的8条BUY/SELL规则。

    【当前数据】
    - 价格: ${price_data['price']:,.2f} | 变化: {price_data['price_change']:+.2f}% | 时间: {price_data['timestamp']}
    - RSI: {price_data['technical_data'].get('rsi', 0):.1f}
    - 布林带位置: {bb_position:.3f} (0=下轨,1=上轨)
    - MACD方向: {price_data['trend_analysis'].get('macd', 'N/A')}
    - 趋势: {technical['primary_trend']} | 强度: {trend_score}/10 | 结构: {structure_str}
    - 资金费率: {price_data.get('funding_rate', 0.0):.4%}
    - 波动率: {calculate_volatility(price_data['full_data']):.2%}
    {sentiment_text}

    【绝对禁止】
    - 逆4H趋势下单；框架<2个对齐；资金费率>|0.03%|；BUY RSI>75或<45；SELL RSI>55或<25；ATR>3x平均；重大事件前2小时。

    【BUY 8条 (全部满足才BUY，否则HOLD)】
    1) 4H: SMA5 > SMA20 > SMA50 且价> SMA50
    2) 1H: SMA5 > SMA20 且价> SMA20
    3) 15m: SMA5 上穿 SMA20 (黄金交叉)
    4) MACD: >Signal 或柱线转绿
    5) RSI: 45-75 区间
    6) 资金费率: -0.01% ~ +0.02%; +0.02~+0.03%减仓提示; >+0.03% 禁止
    7) 布林带位置: 0.3-0.7
    8) 成交量: 当前>20周期均量×1.2

    【SELL 8条 (全部满足才SELL，否则HOLD)】
    1) 4H: SMA5 < SMA20 < SMA50 且价< SMA50
    2) 1H: SMA5 < SMA20 且价< SMA20
    3) 15m: SMA5 下穿 SMA20 (死亡交叉)
    4) MACD: <Signal 或柱线转红
    5) RSI: 25-55 区间
    6) 资金费率: -0.02% ~ +0.01%; -0.03~-0.02%减仓提示; <-0.03% 禁止
    7) 布林带位置: 0.3-0.7
    8) 成交量: 当前>20周期均量×1.2

    【风控与收益】
    - 目标风险收益比≥1:2 (可至1:3)；止盈需包含0.15%手续费缓冲。
    - 输出仓位建议仅为相对强弱，最终下单由Python控制，不得改参数。

    按下列JSON回复，不要输出其他内容：
    {{
        "signal": "BUY|SELL|HOLD",
        "confidence": "HIGH|MEDIUM|LOW",
        "reason": "一句话原因，点出不满足的条目或满足的关键条目",
        "risk_assessment": "低风险|中风险|高风险",
        "stop_loss_pct": float,
        "take_profit_pct": float,
        "funding_rate": {price_data.get('funding_rate', 0.0):.6f},
        "rsi": {price_data['technical_data'].get('rsi', 0):.2f}
    }}
    """

    # ------------------------------------------------------------------
    # Private: JSON utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_json_parse(json_str: str) -> Optional[dict]:
        """Parse JSON tolerantly, fixing common formatting issues."""
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            try:
                json_str = json_str.replace("'", '"')
                json_str = re.sub(r"(\w+):", r'"\1":', json_str)
                json_str = re.sub(r",\s*}", "}", json_str)
                json_str = re.sub(r",\s*]", "]", json_str)
                return json.loads(json_str)
            except json.JSONDecodeError as exc:
                print(f"JSON解析失败，原始内容: {json_str}\n错误详情: {exc}")
                return None


# Module-level singleton — for use by ai_commander.py
ai_service = AIService(
    cfg=_default_config,
    signal_svc=_default_signals,
    sentiment_svc=_default_sentiment,
)
