## Role Lister / Purge Bot

### Setup
1. Copy `.env.example` to `.env` and fill in values
   - Required: `DISCORD_TOKEN`, `XC_URL`
   - Common optional values: `ALLOWED_USER_IDS`, `AUDIT_LOG_CHANNEL_ID`, `SS_VOD_ROLE_ID`, `EXPIRED_ROLE_ID`
   - See `.env.example` for inline documentation on every supported env var
2. Build + run:
   - `docker compose up -d --build`

### Rebuild/restart
- `./botup.sh`
- Clean rebuild: `./botup.sh clean`
