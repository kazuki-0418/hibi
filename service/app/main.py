import logging

from fastapi import FastAPI

from .settings import Settings

settings = Settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(title="Personal AI Newspaper API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}
