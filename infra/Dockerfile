# ═══════════════════════════════════════════════════════════════════════
# Dockerfile - MIM-Ops Pro API Server & Solver
# Oracle Cloud Compute Instance 배포용
# ═══════════════════════════════════════════════════════════════════════

FROM python:3.10-slim

LABEL maintainer="workshopcompany"
LABEL description="MIM-Ops Pro API Server - Oracle Cloud Edition"

# 작업 디렉토리
WORKDIR /app

# ─────────────────── 시스템 의존성 설치 ───────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # VTK 및 그래픽 라이브러리
    libvtk9-dev \
    libvtk9.2 \
    # 빌드 도구
    build-essential \
    git \
    # 기타
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# ─────────────────── Python 의존성 설치 ───────────────────
COPY requirements.txt .

RUN pip install --no-cache-dir \
    --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# ─────────────────── 애플리케이션 코드 복사 ───────────────────
COPY . .

# ─────────────────── 디렉토리 생성 ───────────────────
RUN mkdir -p /app/results /app/logs /tmp/mim-ops

# ─────────────────── 환경 변수 설정 ───────────────────
ENV FLASK_APP=api/server.py \
    FLASK_ENV=production \
    PYTHONUNBUFFERED=1 \
    API_HOST=0.0.0.0 \
    API_PORT=5000

# ─────────────────── 헬스 체크 ───────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# ─────────────────── 포트 노출 ───────────────────
EXPOSE 5000

# ─────────────────── 실행 ───────────────────
# Gunicorn을 사용하여 프로덕션급 WSGI 서버 실행
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "4", \
     "--worker-class", "sync", \
     "--timeout", "300", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "api.server:app"]
