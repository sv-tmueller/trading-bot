# IBKR Gateway on the VPS — Setup Notes

The rules-engine bot requires IB Gateway (or TWS) running as a long-lived
process on the VPS. The bot's cron jobs (`daily_check.py`, `monitor/kill_switch.py`)
connect to it via `ib_insync` on `127.0.0.1`.

## 1. Install IB Gateway

Download from https://www.interactivebrokers.com/en/trading/ibgateway-stable.php

The "stable" build is sufficient. Install in `/opt/ibgateway/`.

## 2. Configure auto-login

Recommended: use the IBC project (https://github.com/IbcAlpha/IBC) to auto-login
non-interactively. Without IBC, you'll need to type credentials each restart.

Configure `IBC/config.ini`:
- `IbLoginId=<your-username>`
- `IbPassword=<your-password>` (or use an environment variable)
- `TradingMode=paper` (or `live`)
- `ReadOnlyApi=no`

## 3. Configure API in IB Gateway

Once running:
- File → Global Configuration → API → Settings
- Enable: "Enable ActiveX and Socket Clients"
- Set: "Socket port" = `4002` (paper) or `4001` (live)
- "Trusted IPs" → add `127.0.0.1`
- Disable: "Read-Only API" (the bot needs to place orders)

## 4. systemd service

Create `/etc/systemd/system/ibgateway.service`:

```ini
[Unit]
Description=IB Gateway (auto-login via IBC)
After=network.target

[Service]
Type=simple
User=trader
ExecStart=/opt/ibgateway/IBC/scripts/ibcstart.sh PAPER
Restart=on-failure
RestartSec=30s

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ibgateway
sudo systemctl start ibgateway
sudo systemctl status ibgateway
```

## 5. Verify connectivity

From the trader user:
```bash
cd /opt/trading-bot
venv/bin/python -c "
from ib_insync import IB
ib = IB()
ib.connect('127.0.0.1', 4002, clientId=99)
print('connected:', ib.isConnected())
print('account:', ib.managedAccounts())
ib.disconnect()
"
```

Expected: `connected: True`, account list non-empty.

## 6. Daily reset

IB Gateway forces a daily logout around 22:30 ET (~03:30 UTC). With IBC + the
systemd service above, it will auto-login again within ~30 seconds. Our cron
windows (`30 22 * * 1-5` UTC daily, `5 14-21 * * 1-5` UTC hourly) avoid this
window entirely.

If you see `tws_disconnected` notifications outside the reset window, check
`journalctl -u ibgateway -n 100` for the cause.
