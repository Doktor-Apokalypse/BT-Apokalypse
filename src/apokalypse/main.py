"""Application entry point."""

def run() -> None:
    """Run the web application."""
    import uvicorn

    uvicorn.run("apokalypse.web:app", host="127.0.0.1", port=8080)


if __name__ == "__main__":
    run()
