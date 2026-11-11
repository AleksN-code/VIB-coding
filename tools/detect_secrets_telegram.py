"""Плагін detect-secrets: шукає Telegram bot token у будь-якому місці рядка.

Вбудований TelegramBotTokenDetector знаходить токен, лише якщо він займає весь рядок,
тому не бачить, наприклад, BOT_TOKEN = "123456789:AA...". Цей плагін це виправляє.
"""

import re

from detect_secrets.plugins.base import RegexBasedDetector


class TelegramTokenInLineDetector(RegexBasedDetector):
    """Telegram bot token (<id>:<ключ>) у будь-якому місці рядка."""

    secret_type = "Telegram Bot Token (in line)"  # pragma: allowlist secret

    denylist = [
        re.compile(r"(?<![0-9])[0-9]{8,10}:[0-9A-Za-z_-]{30,}"),
    ]
