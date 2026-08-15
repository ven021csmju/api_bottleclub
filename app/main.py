from fastapi import FastAPI
from app.routers import users, products

app = FastAPI(
    title="FastAPI + PostgreSQL",
    description="Simple REST API with FastAPI, SQLAlchemy, and PostgreSQL",
    version="1.0.0",
)

# Register routers
app.include_router(users.router)
app.include_router(products.router)


@app.get("/")
def root():
    return {"message": "FastAPI is running"}
