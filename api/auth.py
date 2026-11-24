"""Базовий захист web-адмінки паролем ADMIN_PASSWORD.

Навчальний рівень, а не повноцінна авторизація:
- один спільний пароль, без користувачів і ролей;
- пароль — лише у файлі .env (у Git не потрапляє), його отримує тільки сервіс api;
- після правильного пароля backend видає сесію в cookie з прапорцем HttpOnly —
  JavaScript сторінки її не бачить, тож навіть шкідливий скрипт не вкраде сесію;
- сесія підписана (HMAC) ключем, отриманим з пароля: підробити її без пароля не можна,
  а зміна пароля в .env одразу скасовує всі видані сесії;
- після кількох невдалих спроб вхід тимчасово блокується.

Адмінка однаково працює лише на цьому ПК (127.0.0.1). Перед публікацією в інтернет
потрібні HTTPS (і прапорець Secure для cookie) та повноцінна авторизація.
"""

import hashlib
import hmac
import logging
import secrets
import time
from collections import deque

logger = logging.getLogger("api.auth")

COOKIE_NAME = "admin_session"
SESSION_SECONDS = 12 * 60 * 60  # сесія діє 12 годин
MIN_PASSWORD_LENGTH = 8

# Захист від підбору: не більше MAX_FAILED невдалих спроб за FAILED_WINDOW секунд
MAX_FAILED = 5
FAILED_WINDOW = 60

_password: str | None = None
_problem: str | None = "Пароль адмінки ще не налаштовано."
_failed_at: deque[float] = deque()


def configure(password: str | None) -> None:
    """Читає пароль під час старту API. Якщо пароля немає чи він закороткий — вхід закрито для всіх."""
    global _password, _problem
    _password, _problem = None, None
    if not password:
        _problem = "Пароль адмінки не задано: додайте ADMIN_PASSWORD у файл .env і перезапустіть API."
    elif len(password) < MIN_PASSWORD_LENGTH:
        _problem = (
            f"Пароль адмінки в .env закороткий: потрібно щонайменше {MIN_PASSWORD_LENGTH} символів."
        )
    else:
        _password = password

    if _problem:
        # Сам пароль у лог не пишемо — лише що з ним не так
        logger.error("Вхід в адмінку закрито. %s", _problem)
    else:
        logger.info("Захист адмінки паролем увімкнено")


def problem() -> str | None:
    """Чому вхід неможливий (пароль не налаштовано), або None — усе гаразд."""
    return _problem


def _signing_key() -> bytes:
    # Ключ підпису залежить від пароля: новий пароль — старі сесії недійсні
    return hashlib.sha256(b"car-finance-admin-session:" + _password.encode()).digest()


def _sign(payload: str) -> str:
    return hmac.new(_signing_key(), payload.encode(), hashlib.sha256).hexdigest()


def too_many_attempts() -> bool:
    """Чи заблоковано вхід через забагато невдалих спроб за останню хвилину."""
    now = time.monotonic()
    while _failed_at and now - _failed_at[0] > FAILED_WINDOW:
        _failed_at.popleft()
    return len(_failed_at) >= MAX_FAILED


def check_password(password: str) -> bool:
    """Порівняння за сталий час (compare_digest): з часу відповіді не вгадати, скільки символів збіглося."""
    if _password is None:
        return False
    ok = hmac.compare_digest(password.encode(), _password.encode())
    if not ok:
        _failed_at.append(time.monotonic())
        logger.warning("Невдала спроба входу в адмінку")
    return ok


def new_session() -> str:
    """Підписаний токен сесії: «коли закінчується.випадкове число.підпис»."""
    payload = f"{int(time.time()) + SESSION_SECONDS}.{secrets.token_hex(8)}"
    return f"{payload}.{_sign(payload)}"


def session_valid(token: str | None) -> bool:
    if not token or _password is None:
        return False
    try:
        expires, nonce, signature = token.split(".")
        expires_at = int(expires)
    except ValueError:
        return False
    if not hmac.compare_digest(signature, _sign(f"{expires}.{nonce}")):
        return False
    return expires_at > time.time()
