"""Помилки дій з авто й операціями — спільні для Telegram-бота і web-адмінки.

Текст помилки написаний для людини: бот показує його в чаті,
backend API — у JSON-відповіді, а React — на екрані.
"""


class AppError(Exception):
    """Дію не виконано. `message` — пояснення для користувача."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ValidationError(AppError):
    """Неправильні дані: сума, дата, валюта, рік, VIN тощо. (API: 422)"""


class NotFoundError(AppError):
    """Авто, операцію чи категорію не знайдено — або вона чужа. (API: 404)"""


class ConflictError(AppError):
    """Дані правильні, але суперечать уже записаним: другий продаж авто, VIN уже є. (API: 409)"""


class RateUnavailableError(AppError):
    """Курс НБУ отримати не вдалося — операцію без правильного курсу не записуємо. (API: 503)"""
