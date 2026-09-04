"""
app/__init__.py
Creates the Flask application and registers the pages blueprint.
"""

from flask import Flask


def create_app():
    """Application factory: builds and returns the Flask app."""
    # Flask automatically looks for the 'templates' and 'static'
    # folders inside this 'app' package.
    app = Flask(__name__)

    # Import the blueprint that holds all of the page routes
    # and attach it to the application.
    from app.pages import pages_bp
    app.register_blueprint(pages_bp)

    return app
