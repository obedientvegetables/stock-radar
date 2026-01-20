# Google Cloud Setup Guide for Stock Radar

This guide walks you through deploying Stock Radar to a free-tier Google Cloud VM.

## Cost Summary

**Free tier includes:**
- 1 e2-micro VM instance per month (us-central1, us-west1, or us-east1)
- 30 GB standard persistent disk
- 1 GB network egress per month

**Expected cost: $0/month** (if you stay within free tier limits)

---

## Part 1: Create Google Cloud Account

### Step 1.1: Sign Up

1. Go to https://cloud.google.com
2. Click **"Get started for free"** (top right)
3. Sign in with your Google account
4. You'll get $300 free credit for 90 days (not needed for free tier, but nice to have)

### Step 1.2: Add Billing

Even for free tier, Google requires a billing account:

1. Go to https://console.cloud.google.com/billing
2. Click **"Link a billing account"** or **"Create account"**
3. Enter payment method (credit card)
4. **Important:** You won't be charged for free tier usage

### Step 1.3: Enable Budget Alerts (Recommended)

Protect yourself from accidental charges:

1. Go to **Billing** > **Budgets & alerts**
2. Click **"Create budget"**
3. Set budget to **$1/month**
4. Enable email alerts at 50%, 90%, 100%

---

## Part 2: Create Project

### Step 2.1: Create New Project

1. Go to https://console.cloud.google.com
2. Click the project dropdown (top left, next to "Google Cloud")
3. Click **"New Project"**
4. Enter:
   - **Project name:** `stock-radar`
   - **Location:** Leave as "No organization"
5. Click **"Create"**
6. Wait for creation (30 seconds)
7. **Note your Project ID** (shown below project name, like `stock-radar-123456`)

### Step 2.2: Select the Project

1. Click the project dropdown again
2. Click on **"stock-radar"** to select it
3. Verify it shows "stock-radar" in the top bar

---

## Part 3: Create VM Instance

### Step 3.1: Enable Compute Engine API

1. Go to **Navigation menu** (☰) > **Compute Engine** > **VM instances**
2. If prompted, click **"Enable"** to enable the Compute Engine API
3. Wait 1-2 minutes for API to enable

### Step 3.2: Create the VM

1. Click **"Create Instance"**

2. Configure **Name and region:**
   - **Name:** `stock-radar-vm`
   - **Region:** `us-central1 (Iowa)` ← Free tier eligible
   - **Zone:** `us-central1-a` (any zone is fine)

3. Configure **Machine configuration:**
   - **Series:** `E2`
   - **Machine type:** `e2-micro (2 vCPU, 1 GB memory)` ← Free tier

4. Configure **Boot disk:**
   - Click **"Change"**
   - **Operating system:** `Ubuntu`
   - **Version:** `Ubuntu 22.04 LTS`
   - **Boot disk type:** `Standard persistent disk` ← Free tier (not SSD!)
   - **Size:** `20` GB
   - Click **"Select"**

5. Configure **Firewall:**
   - ✅ Check **"Allow HTTP traffic"**
   - ✅ Check **"Allow HTTPS traffic"**

6. Click **"Create"**

7. Wait 1-2 minutes for VM to start
8. **Note the External IP** (shown in the VM list, like `35.192.123.456`)

---

## Part 4: Set Up Firewall for Dashboard (Port 5001)

### Step 4.1: Create Firewall Rule

1. Go to **Navigation menu** (☰) > **VPC network** > **Firewall**
2. Click **"Create Firewall Rule"**
3. Configure:
   - **Name:** `allow-stock-radar-dashboard`
   - **Network:** `default`
   - **Priority:** `1000`
   - **Direction of traffic:** `Ingress`
   - **Action on match:** `Allow`
   - **Targets:** `All instances in the network`
   - **Source filter:** `IPv4 ranges`
   - **Source IPv4 ranges:** `0.0.0.0/0`
   - **Protocols and ports:** Select **"Specified protocols and ports"**
     - ✅ Check **TCP**
     - Enter: `5001`
4. Click **"Create"**

---

## Part 5: Connect to Your VM

### Option A: Browser SSH (Easiest)

1. Go to **Compute Engine** > **VM instances**
2. Find `stock-radar-vm`
3. Click **"SSH"** button in the Connect column
4. A new browser window opens with terminal access

### Option B: Terminal SSH (Recommended for regular use)

#### First time setup:

1. Install Google Cloud CLI:
   ```bash
   # macOS
   brew install google-cloud-sdk

   # Or download from https://cloud.google.com/sdk/docs/install
   ```

2. Initialize and authenticate:
   ```bash
   gcloud init
   ```
   - Select your Google account
   - Select project `stock-radar`
   - Select default region `us-central1-a`

3. Create SSH keys:
   ```bash
   gcloud compute ssh stock-radar-vm --zone=us-central1-a
   ```
   - First time will create keys automatically
   - Accept defaults for passphrase (or set one)

#### Regular connections:

```bash
# Using gcloud (handles keys automatically)
gcloud compute ssh stock-radar-vm --zone=us-central1-a

# Or using standard SSH with your VM's external IP
ssh YOUR_USERNAME@EXTERNAL_IP
```

---

## Part 6: Initial Server Setup

### Step 6.1: Connect to VM

Use browser SSH or terminal SSH (from Part 5)

### Step 6.2: Run Setup Script

Once connected to the VM:

```bash
# Download and run the setup script
# Option 1: Copy from your local machine first (see Part 7)
# Option 2: Run commands manually:

sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git sqlite3

mkdir -p ~/stock_radar
cd ~/stock_radar
python3 -m venv venv
source venv/bin/activate
mkdir -p data logs output
```

---

## Part 7: Deploy Your Code

### Step 7.1: From Your Local Mac

```bash
# Get your VM's external IP from the Cloud Console
# Navigate to your project
cd ~/stock_radar/deployment

# Make deploy script executable
chmod +x deploy.sh

# Deploy (replace with your actual IP)
./deploy.sh 35.192.123.456
```

### Step 7.2: On the Server

```bash
# SSH into the server
gcloud compute ssh stock-radar-vm --zone=us-central1-a

# Activate environment and install dependencies
cd ~/stock_radar
source venv/bin/activate
pip install -r requirements.txt
```

---

## Part 8: Configure Environment

### Step 8.1: Create .env File

On the server:

```bash
cd ~/stock_radar
nano .env
```

Paste your configuration (use the template from env_template.txt):

```
# SEC EDGAR (Required)
SEC_USER_AGENT=StockRadar your-email@example.com

# Email Settings (Required for alerts)
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_USERNAME=your-gmail@gmail.com
EMAIL_PASSWORD=your-app-specific-password
EMAIL_TO=your-email@example.com
EMAIL_FROM=Stock Radar

# API Keys (Optional but recommended)
ADANOS_API_KEY=your_adanos_key_here
```

Press `Ctrl+X`, then `Y`, then `Enter` to save.

### Step 8.2: Initialize Database

```bash
cd ~/stock_radar
source venv/bin/activate
python3 daily_run.py init
python3 daily_run.py status
```

---

## Part 9: Set Up Automated Scheduling

### Step 9.1: Configure Cron Jobs

Google Cloud VMs use UTC timezone. The cron jobs need adjustment:

- 8:00 AM ET = 13:00 UTC (or 12:00 UTC during DST)
- 4:30 PM ET = 21:30 UTC (or 20:30 UTC during DST)

```bash
# Open crontab editor
crontab -e

# Add these lines (using UTC times for EST):
# Morning collection at 8:00 AM EST (13:00 UTC)
0 13 * * 1-5 cd ~/stock_radar && source venv/bin/activate && python3 daily_run.py morning >> logs/cron.log 2>&1

# Evening pipeline at 4:30 PM EST (21:30 UTC)
30 21 * * 1-5 cd ~/stock_radar && source venv/bin/activate && python3 daily_run.py evening >> logs/cron.log 2>&1
```

Save and exit (Ctrl+X, Y, Enter in nano).

### Step 9.2: Verify Cron

```bash
crontab -l
```

---

## Part 10: Run Dashboard (Optional)

### Step 10.1: Start Dashboard

```bash
cd ~/stock_radar
source venv/bin/activate
nohup python3 app.py > logs/dashboard.log 2>&1 &
```

### Step 10.2: Access Dashboard

Open in browser: `http://YOUR_EXTERNAL_IP:5001`

### Step 10.3: Keep Dashboard Running with systemd

Create a service file:

```bash
sudo nano /etc/systemd/system/stock-radar-dashboard.service
```

Paste:

```ini
[Unit]
Description=Stock Radar Dashboard
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/stock_radar
Environment=PATH=/home/YOUR_USERNAME/stock_radar/venv/bin
ExecStart=/home/YOUR_USERNAME/stock_radar/venv/bin/python3 app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Replace `YOUR_USERNAME` with your actual username.

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable stock-radar-dashboard
sudo systemctl start stock-radar-dashboard
sudo systemctl status stock-radar-dashboard
```

---

## Part 11: Test Everything

### Step 11.1: Test Data Collection

```bash
cd ~/stock_radar
source venv/bin/activate

# Test insider collection
python3 daily_run.py insider-collect --count 10

# Check database
python3 daily_run.py status
```

### Step 11.2: Test Email (Optional)

```bash
python3 daily_run.py email --test
```

### Step 11.3: Test Full Pipeline

```bash
python3 daily_run.py evening
```

---

## Troubleshooting

### VM Won't Start
- Check you selected `e2-micro` (not a larger machine)
- Verify region is free-tier eligible (us-central1, us-west1, us-east1)

### Can't Connect via SSH
- Wait 2-3 minutes after VM creation
- Try browser SSH first
- Check firewall allows SSH (port 22) - it's on by default

### Dashboard Not Accessible
- Verify firewall rule for port 5001 exists
- Check dashboard is running: `ps aux | grep app.py`
- Verify external IP is correct

### Cron Jobs Not Running
- Check timezone: `date` should show UTC
- Verify cron syntax: `crontab -l`
- Check logs: `tail -f ~/stock_radar/logs/cron.log`

### Out of Memory
- e2-micro has 1GB RAM, which is tight
- If issues occur, consider upgrading to e2-small ($6.11/month)
- Or optimize by running only essential tasks

---

## Quick Reference

| Task | Command |
|------|---------|
| SSH into server | `gcloud compute ssh stock-radar-vm --zone=us-central1-a` |
| Start dashboard | `cd ~/stock_radar && source venv/bin/activate && python3 app.py` |
| View cron logs | `tail -f ~/stock_radar/logs/cron.log` |
| Check processes | `ps aux \| grep python` |
| Restart dashboard service | `sudo systemctl restart stock-radar-dashboard` |
| Deploy code update | `./deployment/deploy.sh YOUR_VM_IP` |
| Check VM status | Cloud Console > Compute Engine > VM instances |

---

## Stopping/Starting the VM

To save resources when not needed:

**Stop VM:**
1. Go to Compute Engine > VM instances
2. Click checkbox next to `stock-radar-vm`
3. Click **"Stop"** (top menu)

**Start VM:**
1. Click checkbox next to `stock-radar-vm`
2. Click **"Start"** (top menu)
3. Note: External IP may change!

**Tip:** Use a static IP to keep the same address ($0 while VM is running, $0.01/hr when stopped)
