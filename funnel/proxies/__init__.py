"""Proxies for run-time access."""

from flask import Flask

from .request import request_wants, response_varies


def init_app(app: Flask) -> None:
    """Make proxies available in Jinja templates."""
    app.jinja_env.globals['request_wants'] = request_wants
    app.after_request(response_varies)
