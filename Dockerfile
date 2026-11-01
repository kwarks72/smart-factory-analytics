# Linux(Debian) 위에 파이썬이 설치된 기본 상자를 가져옵니다
FROM python:3.12-slim

# 그래프의 한글이 깨지지 않도록 나눔 폰트 설치
RUN apt-get update && apt-get install -y --no-install-recommends fonts-nanum \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000 8501
# 기본 실행: API 서버 (docker-compose가 서비스별로 다른 명령을 덮어씁니다)
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
