FROM python:3.12-slim

# Рабочая директория внутри контейнера
WORKDIR /app

# Копируем всё необходимое
COPY backend/ ./backend/
COPY static/ ./static/
COPY requirements.txt .
RUN pip install -r requirements.txt

# Открываем порт
EXPOSE 8000

# Запуск
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]