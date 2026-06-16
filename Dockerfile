FROM python:3.12-slim

# Рабочая директория внутри контейнера
WORKDIR /app

# Копируем requirements и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код из папки app
COPY app/ .

# Открываем порт
EXPOSE 8000

# Запуск
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]