"""Isolated UI test server. No external collection or production database."""
from app.main import create_app

app = create_app(scheduler=False)
