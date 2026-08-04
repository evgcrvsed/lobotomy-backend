FROM python:3.12-slim

# Без этого print() буферизуется и сообщения не попадают в docker logs
ENV PYTHONUNBUFFERED=1

# Рабочая директория внутри контейнера
WORKDIR /app

# Копируем всё необходимое
COPY backend/ ./backend/
COPY static/ ./static/
COPY requirements.txt .
RUN pip install -r requirements.txt

# Т-Банк подписывает свой сертификат российским корневым УЦ (Минцифры) —
# его нет в стандартном наборе доверенных сертификатов (certifi), поэтому
# httpx падал с "self-signed certificate in certificate chain" при обращении
# к Т-Банку с настоящими (не demo) ключами. Сертификаты — официальные,
# с gu-st.ru (Госуслуги), лежат в backend/certs, sha256 сверен вручную
# с тем, что реально шлёт securepay.tinkoff.ru.
RUN python -c "\
import certifi; \
bundle = certifi.where(); \
root = open('backend/certs/russian_trusted_root_ca.pem', encoding='utf-8').read().strip(); \
sub = open('backend/certs/russian_trusted_sub_ca.pem', encoding='utf-8').read().strip(); \
open(bundle, 'a', encoding='utf-8').write('\n' + root + '\n' + sub + '\n')"

# Открываем порт
EXPOSE 8000

# Запуск
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]