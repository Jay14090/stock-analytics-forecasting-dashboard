"""Flask extension singletons.

Kept in their own module so models, services and the app factory can import
them without creating a circular dependency back through ``app/__init__``.
"""

from __future__ import annotations

from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


db = SQLAlchemy(model_class=Base)
cors = CORS()
