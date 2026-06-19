FROM python:3.12-slim

ENV TZ=Asia/Ho_Chi_Minh

RUN apt-get update && apt-get install -y tzdata

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY weatherAPI.py .
COPY telegrambot.py .
COPY lunarcalendar.py .

CMD ["python", "main.py"]
