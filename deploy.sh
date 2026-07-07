#!/bin/bash

# Exit on error
set -e

echo "Starting Low-Memory Deployment Process..."

# Variables
REPO_URL=${REPO_URL:-"YOUR_GITHUB_REPO_URL"}
APP_DIR=${APP_DIR:-"/home/ubuntu/java-bms"}

echo "1. Updating system and installing dependencies..."
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git

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
