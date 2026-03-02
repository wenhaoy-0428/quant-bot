"""Sentiment service.

Wraps the CryptoOracle sentiment HTTP API with monitoring and graceful
degradation.  Replaces ``get_sentiment_indicators()`` and
``check_sentiment_api_health()`` from ``trading_bots/signals.py``.

The monitor state (consecutive failures, success rate, etc.) that used to
live as a bare module-level dict now lives as ``SentimentService._monitor``.
"""

import os
import traceback
from datetime import datetime, timedelta

import requests


class SentimentService:
    """Fetches BTC market-sentiment data from the CryptoOracle API.

    Implements automatic circuit-breaking: after 5 consecutive failures
    requests are skipped until the service recovers.
    """

    _API_URL = "https://service.cryptoracle.network/openapi/v2/endpoint"

    def __init__(self) -> None:
        self._monitor: dict = {
            "last_check": None,
            "last_success": None,
            "consecutive_failures": 0,
            "is_available": True,
            "failure_count_today": 0,
            "last_error": None,
            "total_requests": 0,
            "successful_requests": 0,
            "last_reset_date": datetime.now().date(),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_indicators(self) -> dict | None:
        """Return the latest 4-hour sentiment snapshot, or None on failure."""
        self._reset_daily_counters_if_needed()

        api_key = os.getenv("CRYPTORACLE_API_KEY", "")
        m = self._monitor
        m["last_check"] = datetime.now()
        m["total_requests"] += 1

        if not api_key:
            print("⚠️ 市场情绪API密钥未配置，跳过情绪分析")
            m["is_available"] = False
            return None

        if m["consecutive_failures"] >= 5:
            print(f"⚠️ 市场情绪API连续失败{m['consecutive_failures']}次，暂停使用")
            m["is_available"] = False
            return None

        return self._fetch(api_key)

    def health_check(self) -> str:
        """Return a human-readable status string for the sentiment API."""
        m = self._monitor

        if m["last_check"] is None:
            return "未检查"

        if not m["is_available"]:
            return f"不可用 (连续失败{m['consecutive_failures']}次)"

        if m["last_success"]:
            mins = (datetime.now() - m["last_success"]).total_seconds() / 60
            if mins > 30:
                return f"警告 (上次成功: {mins:.1f}分钟前)"

        success_rate = 0.0
        if m["total_requests"] > 0:
            success_rate = m["successful_requests"] / m["total_requests"] * 100

        return f"正常 (成功率: {success_rate:.1f}%, 今日失败: {m['failure_count_today']}次)"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _reset_daily_counters_if_needed(self) -> None:
        today = datetime.now().date()
        if self._monitor["last_reset_date"] != today:
            self._monitor["failure_count_today"] = 0
            self._monitor["last_reset_date"] = today
            print("🔄 市场情绪API监控：每日计数器已重置")

    def _record_failure(self, error_msg: str) -> None:
        m = self._monitor
        m["consecutive_failures"] += 1
        m["failure_count_today"] += 1
        m["last_error"] = error_msg
        print(f"⚠️ 市场情绪API: {error_msg}")

    def _fetch(self, api_key: str) -> dict | None:
        """Execute the actual HTTP request and parse the response."""
        now = datetime.now()
        body = {
            "apiKey": api_key,
            "endpoints": ["CO-A-02-01", "CO-A-02-02"],
            "startTime": (now - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S"),
            "endTime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "timeType": "15m",
            "token": ["BTC"],
        }
        headers = {"Content-Type": "application/json", "X-API-KEY": api_key}

        try:
            resp = requests.post(self._API_URL, json=body, headers=headers, timeout=10)

            if resp.status_code != 200:
                self._record_failure(f"HTTP错误: {resp.status_code}")
                return None

            data = resp.json()
            if not (data.get("code") == 200 and data.get("data")):
                self._record_failure(
                    f"API返回错误码: {data.get('code', 'unknown')}, 消息: {data.get('msg', 'unknown')}"
                )
                return None

            for period in data["data"][0]["timePeriods"]:
                result = self._parse_period(period)
                if result is not None:
                    m = self._monitor
                    m["consecutive_failures"] = 0
                    m["is_available"] = True
                    m["last_success"] = datetime.now()
                    m["successful_requests"] += 1
                    m["last_error"] = None
                    positive = result["positive_ratio"]
                    negative = result["negative_ratio"]
                    net = result["net_sentiment"]
                    delay = result["data_delay_minutes"]
                    print(
                        f"✅ 市场情绪API正常: 乐观{positive:.1%} 悲观{negative:.1%} "
                        f"净值{net:+.3f} (延迟:{delay}分钟)"
                    )
                    return result

            self._record_failure("API返回数据为空")
            return None

        except requests.exceptions.Timeout:
            self._record_failure("请求超时（超过10秒）")
        except requests.exceptions.ConnectionError:
            self._record_failure("连接错误（无法连接到服务器）")
        except Exception as exc:
            self._record_failure(f"未知错误: {exc}")
            traceback.print_exc()
        return None

    @staticmethod
    def _parse_period(period: dict) -> dict | None:
        """Extract positive/negative ratios from one time-period block."""
        sentiment: dict = {}
        for item in period.get("data", []):
            endpoint = item.get("endpoint")
            value = item.get("value", "").strip()
            if value and endpoint in ("CO-A-02-01", "CO-A-02-02"):
                try:
                    sentiment[endpoint] = float(value)
                except (ValueError, TypeError):
                    continue

        if "CO-A-02-01" not in sentiment or "CO-A-02-02" not in sentiment:
            return None

        positive = sentiment["CO-A-02-01"]
        negative = sentiment["CO-A-02-02"]
        delay = int(
            (datetime.now() - datetime.strptime(period["startTime"], "%Y-%m-%d %H:%M:%S")).total_seconds() // 60
        )
        return {
            "positive_ratio": positive,
            "negative_ratio": negative,
            "net_sentiment": positive - negative,
            "data_time": period["startTime"],
            "data_delay_minutes": delay,
        }


# Module-level singleton
sentiment_service = SentimentService()
