"""
Módulo de APIs utilitárias externas.
"""

from apis.base import ApiRegistry, CircuitBreaker, CircuitBreakerError, RateLimiter
from apis.colors import fetch_color_name, fetch_color_palette
from apis.emojis import fetch_emoji_search
from apis.topics import fetch_topic_suggest
from apis.translate import fetch_translation

__all__ = [
    "ApiRegistry",
    "CircuitBreaker",
    "CircuitBreakerError",
    "RateLimiter",
    "fetch_color_palette",
    "fetch_color_name",
    "fetch_emoji_search",
    "fetch_topic_suggest",
    "fetch_translation",
]
