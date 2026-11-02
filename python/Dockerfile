# Сервис АтрибутыАГР (FastAPI). Сборка: из папки deploy — docker compose up -d --build
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 LANG=C.UTF-8
WORKDIR /app
COPY requirements-service.txt .
RUN pip install --no-cache-dir -r requirements-service.txt
# только код; таблицы правил и разметка — в папке data (подключается снаружи)
COPY service.py rules_engine.py rules.py train_model.py train_spaces.py eval_baseline.py build_labels.py ./
EXPOSE 8765
CMD ["python", "service.py"]
