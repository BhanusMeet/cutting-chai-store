# Putting the pitch store online (Render)

**Only the pitch store with sample data.** Do not put real sales or customer details online yet.

## Service settings

| Setting | Value |
|---|---|
| Type | Web service, Python |
| Repository | `BhanusMeet/cutting-chai-store` (private), branch `cutting-chai-pitch-store` |
| Region / plan | Singapore (nearest to India) / Free |
| Build command | `pip install -r qr-order/requirements.txt` |
| Start command | `cd qr-order && python pitch.py --hosted` |
| Health check path | `/api/health` (optional) |

Environment variables set by the setup:

| Name | Value |
|---|---|
| `PYTHON_VERSION` | `3.11.9` |
| `TZ` | `Asia/Kolkata` |
| `QRO_PROXY_HOPS` | to be confirmed after the first deploy (see below) |

**You type these two yourself** in Render -> the service -> Environment. Do not send them to anyone:

- `QRO_PITCH_OWNER_PASSWORD`: at least 10 characters, one you use nowhere else
- `QRO_PITCH_STAFF_PIN`: 6 to 12 digits, not a simple pattern

Until both are set, the service refuses to start. That is intended.

## After the first deploy

1. Open `https://<service-address>/`, sign in to the owner panel and open **Activity**. The "From" column
   must show your own public internet address. If it shows another address, `QRO_PROXY_HOPS` is wrong and
   one person's wrong tries could block everyone: correct it before sharing the link.
2. Check that a new order appears on the kitchen screen without reloading (live updates through the host).

## What to expect on the free plan

- It sleeps after about 15 minutes without visitors and takes about a minute to wake. **Open it a few
  minutes before a meeting.**
- Its disk is wiped on every sleep, restart or deploy, so the pitch store is rebuilt with fresh sample data.
  Menu edits and orders are lost, and previously printed table QR codes stop working.
- USB printing does not work online (the server cannot reach a printer in a restaurant).
- Sign-ins may be slow on the free plan's small processor.

Limits can change: check https://render.com/docs/free before relying on them.
