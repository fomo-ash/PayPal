"""FastAPI app. Phase 0: health only. Routers are wired in Phase 2."""

from fastapi import FastAPI

app = FastAPI(title="Verdict API", version="0.0.1")


@app.get("/health")
def health() -> dict:
    return {"ok": True}
