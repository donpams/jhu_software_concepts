"""
run.py
Entry point for the personal website.
Start the site with:  python run.py
The site is served on http://0.0.0.0:8080 (open http://localhost:8080 in a browser).
"""

from app import create_app

# Build the Flask application using the factory function in app/__init__.py
app = create_app()

if __name__ == "__main__":
    # host="0.0.0.0" makes the site reachable on localhost and the local network.
    # port=8080 is required by the assignment.
    app.run(host="0.0.0.0", port=8080, debug=True)
