from fastapi import FastAPI

from backend.api.cases import router as cases_router

app = FastAPI(title="Examination Scheduler")
app.include_router(cases_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
