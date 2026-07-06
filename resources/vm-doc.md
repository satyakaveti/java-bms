# Deployment Walkthrough

Congratulations! The FastAPI application has been successfully deployed to your Oracle VM (`129.159.225.102`).

## 🚀 Final Results

The application is now running live as a background systemd service. Because we optimized it for a low-memory (1GB RAM) environment, it's running directly on Port 8282 without Nginx, using a single worker to conserve memory alongside PostgreSQL and Redis.

You can access your live application here:
🔗 **[http://129.159.225.102:8282](http://129.159.225.102:8282)**

## 🛠️ What Was Done

Here is a summary of the automated steps that were executed on your server:

1. **System Preparation**:
    - Installed `python3`, `pip`, `venv`, `git`, and build tools on the Oracle VM.
2. **Code Deployment**:
    - Cloned your GitHub repository (`satyakaveti/java-bms`) into `/home/ubuntu/java-bms`.
    - Created a Python virtual environment and successfully installed all dependencies from `requirements.txt`.
3. **Configuration Fixes**:
    - Transferred your local `.env` file to the server.
    - Identified that the app initially crashed due to a database authentication error (`password authentication failed for user "postgres"`).
    - Swapped the active `DATABASE_URL` in your `.env` file to the production URL containing the correct password (`VG9sbHlCb0...`) and securely updated it on the server.
4. **Service Setup**:
    - Created a systemd service (`fastapi-app.service`).
    - Configured Uvicorn to bind to Port 8282.
    - Added an `iptables` rule to allow incoming TCP traffic on Port 8282.
    - Started the service and verified that it is running cleanly without crashing.

> [!TIP]
> **Checking Logs**: If you ever need to view the live logs of your application to debug issues, you can SSH into your VM and run:
> `sudo journalctl -u fastapi-app.service -f`

> [!WARNING]
> Because Nginx is not installed, the application is currently served over plain HTTP. Ensure you do not expose sensitive user data unless HTTPS is configured via a reverse proxy (like Cloudflare) or a lightweight web server (like Caddy).

Your app is officially live on your Oracle Cloud instance! Let me know if you need to set up any cron jobs or make further changes.


### Important Next Step
Since you changed the port, you will now need to open **Port 8282** in the Oracle Cloud Console instead of Port 80. The steps are the exact same as before:
1. Log in to the **Oracle Cloud Console** and go to **Networking** > **Virtual Cloud Networks**.
2. Click on your VCN, then your **Subnet**, and open the **Default Security List**.
3. Add a new **Ingress Rule**:
    - **Source CIDR:** `0.0.0.0/0`
    - **Destination Port Range:** `8282`
    - **IP Protocol:** TCP

Once you add that rule, you can access your app directly at `http://129.159.225.102:8282/bms-district-api-docs`!