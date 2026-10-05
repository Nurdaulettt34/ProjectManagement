"""Entry point: `flask --app app run`, `gunicorn app:app`."""
from uniflow import create_app

app = create_app()

if __name__ == "__main__":
    app.run()
