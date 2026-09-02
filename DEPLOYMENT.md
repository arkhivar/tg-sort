# Self-hosting `tg-sort`

This guide runs the complete Telegram Topic Sorter on a Linux server you
control instead of Replit.

The application consists of one Flask web process plus a background Telegram
Bot API polling loop. It stores the learned/imported topic roster in
`topics.json`; there is no database.

## Deployment requirements

- Linux server with a stable public or private network address
- Python 3.11 or newer
- Git
- `systemd` (recommended for keeping the service running)
- A bot token created with `@BotFather`
- A forum group where the bot is an administrator with **Manage Topics**

Use one application instance and one Gunicorn worker. The Telegram Bot API
allows only one active `getUpdates` consumer for a bot, and the application’s
sort queue/status are local to the process.

Do not run multiple copies behind a load balancer. If you need high
availability later, move update consumption and roster storage to a deliberate
single-leader design before adding replicas.

## 1. Prepare the server

Create a dedicated service account and application directory:

```bash
sudo useradd --system --create-home --home-dir /opt/tg-sort --shell /usr/sbin/nologin tg-sort
sudo install -d -o tg-sort -g tg-sort -m 0750 /opt/tg-sort
sudo -u tg-sort git clone https://github.com/arkhivar/tg-sort.git /opt/tg-sort
```

If the directory already contains a checkout:

```bash
sudo -u tg-sort git -C /opt/tg-sort remote set-url origin https://github.com/arkhivar/tg-sort.git
sudo -u tg-sort git -C /opt/tg-sort pull --ff-only
```

Create an isolated Python environment and install the project:

```bash
sudo -u tg-sort python3 -m venv /opt/tg-sort/.venv
sudo -u tg-sort /opt/tg-sort/.venv/bin/python -m pip install --upgrade pip
sudo -u tg-sort /opt/tg-sort/.venv/bin/pip install /opt/tg-sort
```

The project’s `pyproject.toml` installs Flask, Gunicorn, and the other runtime
dependencies. No Telethon or MTProto package is required.

## 2. Configure secrets outside Git

Create a root-owned environment file:

```bash
sudo install -d -m 0750 /etc/tg-sort
sudo install -o root -g tg-sort -m 0640 /dev/null /etc/tg-sort/tg-sort.env
sudoedit /etc/tg-sort/tg-sort.env
```

Put only these values in the file:

```text
BOT_TOKEN=replace-with-the-token-from-BotFather
SESSION_SECRET=replace-with-a-long-random-value
```

Generate a Flask session secret without putting it in shell history:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Never commit this file, print the token in logs, or put the token into
frontend code. The application does not need `API_ID`, `API_HASH`,
`PHONE_NUMBER`, or a personal Telegram session.

## 3. Configure the Telegram bot

In Telegram:

1. Create or choose the bot in `@BotFather`.
2. Add it to each target forum group.
3. Promote it to administrator with **Manage Topics**.
4. Disable privacy mode in `@BotFather` if it should learn ordinary messages
   without a mention.
5. For existing topics, send one controlled message such as
   `hello @tg_sort_bot` in each topic.
6. Use the web UI’s **Load known topics** button to confirm the roster.

The Bot API cannot enumerate historical group topics automatically. The
one-message bootstrap is intentional and is safer than using a personal
account through MTProto. See [EVOLUTION.md](EVOLUTION.md).

## 4. Create the systemd service

Create `/etc/systemd/system/tg-sort.service`:

```ini
[Unit]
Description=Telegram Topic Sorter
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=tg-sort
Group=tg-sort
WorkingDirectory=/opt/tg-sort
EnvironmentFile=/etc/tg-sort/tg-sort.env
ExecStart=/opt/tg-sort/.venv/bin/gunicorn --bind 127.0.0.1:5000 --workers 1 --access-logfile - --error-logfile - main:app
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWritePaths=/opt/tg-sort

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tg-sort
sudo systemctl status tg-sort
sudo journalctl -u tg-sort -f
```

The service binds to `127.0.0.1`, not the public network. Keep it that way
unless the server is protected by a trusted private network.

## 5. Access the web UI safely

The current web UI does not have its own user login. Do **not** expose port
5000 directly to the public internet: anyone who can reach the UI could
request a sort operation.

Safer choices, from simplest to most public-facing:

### SSH tunnel for private administration

From your workstation:

```bash
ssh -N -L 5000:127.0.0.1:5000 your-user@your-server
```

Then open `http://127.0.0.1:5000` locally. The Telegram bot continues running
even after the browser is closed.

### VPN or private network

Place the server and your workstation on a VPN or private network, and allow
the UI only from that network.

### Reverse proxy

If you need browser access from outside your private network, put Nginx,
Caddy, or another reverse proxy in front of the service. Require HTTPS and
authentication at the proxy, and proxy only to `127.0.0.1:5000`.

Example Nginx location after adding your own TLS and authentication:

```nginx
location / {
    proxy_pass http://127.0.0.1:5000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Do not rely on an unprotected public URL as the application’s security
boundary.

## 6. Verify the deployment

From the server:

```bash
curl -fsS http://127.0.0.1:5000/auth_status
curl -fsS http://127.0.0.1:5000/status
```

`/auth_status` should report:

- `configured: true`
- `connected: true`
- the bot identity
- `poller.running: true`

Enter a group username or numeric chat ID in the UI and use **Load known
topics**. The roster is served from `topics.json`.

If the bot does not connect, check:

```bash
sudo journalctl -u tg-sort --since "10 minutes ago"
```

Common causes are an incorrect token, a second process polling the same bot,
or an existing webhook. This application uses long polling and must not share
the bot with another `getUpdates` consumer.

## Updating the server

Stop the service before replacing the application so there is never a second
polling process:

```bash
sudo systemctl stop tg-sort
sudo -u tg-sort git -C /opt/tg-sort pull --ff-only
sudo -u tg-sort /opt/tg-sort/.venv/bin/pip install /opt/tg-sort
sudo systemctl start tg-sort
sudo systemctl status tg-sort
```

After a code update, verify `/auth_status`, the UI, and the known-topic roster.

## Backups and migration

Back up the roster and environment file separately:

```bash
sudo install -o root -g root -m 0600 /opt/tg-sort/topics.json /root/tg-sort-topics.json
sudo install -o root -g root -m 0600 /etc/tg-sort/tg-sort.env /root/tg-sort.env.backup
```

The environment file contains the bot token and must be stored like a
credential. The roster contains topic IDs and metadata but should still be
treated as private group information.

To migrate from Replit:

1. Securely copy `topics.json` to `/opt/tg-sort/topics.json`.
2. Set ownership to the service account:
   ```bash
   sudo chown tg-sort:tg-sort /opt/tg-sort/topics.json
   ```
3. Create the new server’s environment file.
4. Stop the Replit polling workflow before starting the self-hosted service.
5. Start the systemd service and verify that polling is active.

Never run the Replit poller and self-hosted poller at the same time.

## Token rotation and shutdown

If the token is exposed, revoke or regenerate it with `@BotFather`, replace
`BOT_TOKEN` in `/etc/tg-sort/tg-sort.env`, and restart:

```bash
sudo systemctl restart tg-sort
```

To stop the bot safely:

```bash
sudo systemctl stop tg-sort
```

Stopping the service prevents it from consuming updates. It does not delete
the bot, group topics, or roster.

## Architecture boundary

This deployment guide intentionally preserves the project decision in
[EVOLUTION.md](EVOLUTION.md): regular Bot API mode is the default. Do not
replace it with a userbot, Telethon, MTProto, `API_HASH`, or personal login
just to obtain automatic historical topic enumeration. Reconsider that only
after every safe Bot API, bootstrap, import/export, and manual-roster option
has been proven insufficient for an essential requirement and the owner has
approved the risk explicitly.
