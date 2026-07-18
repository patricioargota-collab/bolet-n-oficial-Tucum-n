FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

# Railway inyecta la variable PORT; el server la lee en tiempo de ejecucion.
# NO declarar VOLUME: Railway gestiona los volumenes desde la UI.
CMD ["python", "server.py"]
