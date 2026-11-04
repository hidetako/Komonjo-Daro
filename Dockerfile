FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# NDL古典籍OCR-Lite（CC BY 4.0, 国立国会図書館）をイメージ内に取得
RUN git clone --depth 1 https://github.com/ndl-lab/ndlkotenocr-lite /app/vendor/ndlkotenocr-lite
COPY . .
ENV KOBUN_HOST=0.0.0.0 KOBUN_PORT=5000
EXPOSE 5000
CMD ["python", "app.py"]
