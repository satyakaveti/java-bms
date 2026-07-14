#!/bin/bash

# Exit on error
set -e

echo "Starting Low-Memory Deployment Process..."

# Variables
REPO_URL=${REPO_URL:-"YOUR_GITHUB_REPO_URL"}
APP_DIR=${APP_DIR:-"/home/ubuntu/java-bms"}

echo "1. Updating system and installing dependencies..."
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git tor

echo "1.1 Configuring Tor ControlPort..."
if [ -f /etc/tor/torrc ]; then
    # Ensure ControlPort 9051 is enabled and CookieAuthentication is 0
    if ! sudo grep -q "^ControlPort 9051" /etc/tor/torrc; then
        echo "ControlPort 9051" | sudo tee -a /etc/tor/torrc
    fi
    if ! sudo grep -q "^CookieAuthentication 0" /etc/tor/torrc; then
        echo "CookieAuthentication 0" | sudo tee -a /etc/tor/torrc
    fi
    # Optimize Tor for Indian scraper context (ExitNodes IN, MaxCircuitDirtiness 30)
    if ! sudo grep -q "^ExitNodes" /etc/tor/torrc; then
        echo "ExitNodes {in}" | sudo tee -a /etc/tor/torrc
    fi
    if ! sudo grep -q "^StrictNodes" /etc/tor/torrc; then
        echo "StrictNodes 1" | sudo tee -a /etc/tor/torrc
    fi
    if ! sudo grep -q "^MaxCircuitDirtiness" /etc/tor/torrc; then
        echo "MaxCircuitDirtiness 30" | sudo tee -a /etc/tor/torrc
    fi
    echo "Restarting Tor service..."
    sudo systemctl restart tor
    sudo systemctl enable tor
else
    echo "Warning: /etc/tor/torrc not found, Tor configuration skipped."
fi

echo "2. Setting up application directory..."
if [ ! -d "$APP_DIR" ]; then
    git clone $REPO_URL $APP_DIR
else
    echo "Directory exists, pulling latest changes..."
    cd $APP_DIR
    git fetch origin
    git checkout main
    git reset --hard origin/main
fi

cd $APP_DIR

echo "3. Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

echo "4. Setting up systemd service for FastAPI (Port 80 directly)..."
cat <<EOF | sudo tee /etc/systemd/system/fastapi-app.service
[Unit]
Description=Uvicorn instance to serve FastAPI App
After=network.target

[Service]
User=$USER
Group=$USER
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"

# Allow non-root user to bind to port 80
AmbientCapabilities=CAP_NET_BIND_SERVICE

# Run Uvicorn directly on port 8282 with 1 worker to save memory
ExecStart=$APP_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8282 --workers 1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl start fastapi-app
sudo systemctl enable fastapi-app

echo "Deployment completed successfully! The app should now be listening on Port 80."
echo "Ensure your .env file is securely copied to $APP_DIR/.env"
