# Toy app for probing the validator only: health, register/login, two list endpoints. Everything else is missing.
from fastapi import FastAPI, Header, HTTPException
app = FastAPI()
USERS = {}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/auth/register")
def register(body: dict):
    USERS[body.get("email")] = body.get("password")
    return {"access_token": "tok-" + str(body.get("email")), "token_type": "bearer"}

@app.post("/auth/login")
def login(body: dict):
    if USERS.get(body.get("email")) != body.get("password"):
        raise HTTPException(401, "bad credentials")
    return {"access_token": "tok-" + str(body.get("email")), "token_type": "bearer"}

@app.get("/api/genres")
def genres(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(401, "auth")
    return {"items": [{"id": 1, "name": "Drama"}]}
