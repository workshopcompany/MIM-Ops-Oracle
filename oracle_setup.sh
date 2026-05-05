#!/bin/bash

# ═════════════════════════════════════════════════════════════════════════
# MIM-Ops Pro Oracle Cloud 배포 스크립트
# 사용: chmod +x oracle_setup.sh && ./oracle_setup.sh
# ═════════════════════════════════════════════════════════════════════════

set -e  # 에러 발생 시 중단

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ─────────────────── 함수 정의 ───────────────────
print_header() {
    echo -e "${BLUE}╔════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║ MIM-Ops Pro - Oracle Cloud Setup${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════╝${NC}"
}

print_step() {
    echo -e "\n${BLUE}[*]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

check_command() {
    if ! command -v $1 &> /dev/null; then
        return 1
    fi
    return 0
}

# ─────────────────── 메인 스크립트 ───────────────────

print_header

# 1. 시스템 업데이트
print_step "Updating system packages..."
sudo apt update && sudo apt upgrade -y
print_success "System updated"

# 2. 필수 도구 설치
print_step "Installing essential tools..."
sudo apt install -y \
    python3.10 \
    python3-pip \
    python3-venv \
    git \
    curl \
    wget \
    net-tools \
    htop \
    vim \
    build-essential \
    libvtk9-dev \
    docker.io \
    docker-compose \
    nginx \
    certbot \
    python3-certbot-nginx

print_success "Essential tools installed"

# 3. 일반 사용자 추가 (선택사항)
if ! id -u mim-ops &>/dev/null 2>&1; then
    print_step "Creating 'mim-ops' user..."
    sudo useradd -m -s /bin/bash mim-ops
    print_success "User 'mim-ops' created"
else
    print_warning "User 'mim-ops' already exists"
fi

# 4. 애플리케이션 디렉토리 준비
print_step "Setting up application directory..."
APP_DIR="/opt/mim-ops"
sudo mkdir -p $APP_DIR
sudo chown mim-ops:mim-ops $APP_DIR

cd $APP_DIR

# 5. GitHub 저장소 클론
if [ -d "MIM-Ops-Oracle" ]; then
    print_warning "Repository already exists, pulling latest..."
    cd MIM-Ops-Oracle
    git pull origin main
else
    print_step "Cloning GitHub repository..."
    git clone https://github.com/workshopcompany/MIM-Ops-Oracle.git
    cd MIM-Ops-Oracle
    print_success "Repository cloned"
fi

# 6. Python 가상환경 설정
print_step "Setting up Python virtual environment..."
python3.10 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel
print_success "Virtual environment created"

# 7. 의존성 설치
print_step "Installing Python dependencies..."
pip install -r requirements.txt
print_success "Dependencies installed"

# 8. 환경 변수 설정
print_step "Setting up environment variables..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    print_warning "Created .env file. Please edit it with your Oracle Cloud credentials:"
    print_warning "  nano .env"
else
    print_warning ".env already exists. Skipping template copy."
fi

# 9. 디렉토리 생성
print_step "Creating required directories..."
mkdir -p results logs
mkdir -p /tmp/mim-ops
print_success "Directories created"

# 10. Systemd 서비스 설정
print_step "Setting up systemd service..."
sudo tee /etc/systemd/system/mim-ops-api.service > /dev/null <<EOF
[Unit]
Description=MIM-Ops Pro API Server
After=network.target

[Service]
Type=simple
User=mim-ops
WorkingDirectory=$APP_DIR/MIM-Ops-Oracle
ExecStart=$APP_DIR/MIM-Ops-Oracle/venv/bin/python -m gunicorn \\
    --bind 0.0.0.0:5000 \\
    --workers 4 \\
    --timeout 300 \\
    --access-logfile - \\
    --error-logfile - \\
    api.server:app
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable mim-ops-api
print_success "Systemd service configured"

# 11. Nginx 리버스 프록시 설정
print_step "Configuring Nginx reverse proxy..."
sudo tee /etc/nginx/sites-available/mim-ops > /dev/null <<EOF
server {
    listen 80;
    server_name _;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
    }

    location /stream {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/mim-ops /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
print_success "Nginx configured"

# 12. SSL 인증서 설정 (Let's Encrypt)
print_step "Do you want to set up SSL with Let's Encrypt? (y/n)"
read -r ssl_choice
if [[ "$ssl_choice" =~ ^[Yy]$ ]]; then
    print_step "Setting up SSL certificate..."
    print_warning "Enter your domain name:"
    read -r domain
    
    sudo certbot certonly --nginx -d $domain
    
    # Nginx SSL 설정 업데이트
    sudo tee /etc/nginx/sites-available/mim-ops > /dev/null <<EOF
server {
    listen 80;
    server_name $domain;
    return 301 https://\$server_name\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name $domain;

    ssl_certificate /etc/letsencrypt/live/$domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$domain/privkey.pem;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
    }
}
EOF

    sudo nginx -t
    sudo systemctl restart nginx
    print_success "SSL certificate configured"
else
    print_warning "Skipping SSL setup. Configure manually later."
fi

# 13. 방화벽 설정
print_step "Configuring firewall..."
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
print_success "Firewall configured"

# 14. Oracle Cloud CLI 확인
print_step "Checking Oracle Cloud CLI..."
if ! check_command oci; then
    print_warning "Oracle Cloud CLI not found. Install it with:"
    print_warning "  bash -c \"$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)\""
    print_warning "Then configure: oci setup config"
else
    print_success "Oracle Cloud CLI found"
fi

# 15. 최종 설정
print_step "Finalizing setup..."

# 소유권 설정
sudo chown -R mim-ops:mim-ops $APP_DIR

# 권한 설정
chmod +x $APP_DIR/MIM-Ops-Oracle/api/server.py
chmod +x $APP_DIR/MIM-Ops-Oracle/solver/solver.py

# 디렉토리 권한
sudo chmod 755 /tmp/mim-ops

print_success "Setup completed!"

# ─────────────────── 최종 메시지 ───────────────────

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║ MIM-Ops Pro Setup Complete! ✓${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}"
echo ""

echo -e "${YELLOW}Next Steps:${NC}"
echo ""
echo "1. Edit environment variables:"
echo -e "   ${BLUE}nano $APP_DIR/MIM-Ops-Oracle/.env${NC}"
echo ""
echo "2. Start the API service:"
echo -e "   ${BLUE}sudo systemctl start mim-ops-api${NC}"
echo ""
echo "3. Check service status:"
echo -e "   ${BLUE}sudo systemctl status mim-ops-api${NC}"
echo ""
echo "4. View logs:"
echo -e "   ${BLUE}sudo journalctl -fu mim-ops-api${NC}"
echo ""
echo "5. Access the API:"
echo -e "   ${BLUE}curl http://localhost:5000/health${NC}"
echo ""

echo -e "${YELLOW}Configuration Files:${NC}"
echo "  - .env: $APP_DIR/MIM-Ops-Oracle/.env"
echo "  - Nginx: /etc/nginx/sites-available/mim-ops"
echo "  - Systemd: /etc/systemd/system/mim-ops-api.service"
echo ""

echo -e "${YELLOW}Useful Commands:${NC}"
echo "  - Start:   sudo systemctl start mim-ops-api"
echo "  - Stop:    sudo systemctl stop mim-ops-api"
echo "  - Restart: sudo systemctl restart mim-ops-api"
echo "  - Logs:    sudo journalctl -fu mim-ops-api"
echo ""

echo -e "${BLUE}Documentation:${NC}"
echo "  - GitHub: https://github.com/workshopcompany/MIM-Ops-Oracle"
echo ""
