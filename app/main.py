from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

app = FastAPI(title="Profile Page")

# Монтируем статические файлы под путём /profile
app.mount("/profile",
          StaticFiles(directory="static", html=True),
          name="profile")

# Автоматическое перенаправление с / на /profile
@app.get("/")
async def root():
    return RedirectResponse(url="/profile", status_code=302)