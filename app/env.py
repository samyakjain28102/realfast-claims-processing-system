"""Load `.env` into os.environ for local development."""


def load_env() -> None:
    """Load a `.env` file if python-dotenv is installed."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()
