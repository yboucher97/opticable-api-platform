> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](../../docs/OPTIBRAIN_CODEX_ONBOARDING.md).

# Password PDF Generator

Production-ready WiFi/password PDF generator with:

- FastAPI webhook intake
- fixed-layout PDF rendering with ReportLab
- per-record QR code generation
- merged PDF output
- optional Zoho WorkDrive upload
- Ubuntu installer with systemd and Caddy setup

## Repo Layout

```text
assets/
  wifi_pdf/
config/
  wifi_pdf/
docs/
input/
  wifi_pdf/
wifi_pdf/
install.sh
update.sh
requirements.txt
```

## Quick Install On Ubuntu

Interactive one-command install:

```bash
sudo bash <(curl -fsSL https://raw.githubusercontent.com/yboucher97/Password_PDF_Generator/main/install.sh)
```

The installer will:

- install Ubuntu packages with `apt`
- clone or update the repo into `/opt/password-pdf-generator`
- create the service user and data directories
- create an isolated Python virtual environment and install dependencies inside it
- write runtime config to `/etc/password-pdf-generator/brand_settings.json`
- write secrets to `/etc/password-pdf-generator.env`
- write an install-path inventory text file into the invoking user's home directory
- create and enable `password-pdf-generator.service`
- require a public hostname and configure Caddy automatically
- enable WorkDrive upload by default
- tell you at the end if `/etc/password-pdf-generator.env` still needs any secrets filled in

## Non-Interactive Install

You can also pass values in one command:

```bash
sudo PASSWORD_PDF_HOST=wifi-api.example.com \
PASSWORD_PDF_API_KEY=replace-with-long-random-secret \
bash <(curl -fsSL https://raw.githubusercontent.com/yboucher97/Password_PDF_Generator/main/install.sh)
```

Supported installer variables:

- `PASSWORD_PDF_HOST`
- `PASSWORD_PDF_API_KEY`
- `PASSWORD_PDF_ENABLE_WORKDRIVE`
- `PASSWORD_PDF_ZOHO_REGION`
- `ZOHO_OAUTH_CREDENTIALS_PATH`
- `ZOHO_WORKDRIVE_PARENT_FOLDER_ID`
- `PASSWORD_PDF_INSTALL_DIR`
- `PASSWORD_PDF_DATA_DIR`
- `PASSWORD_PDF_CONFIG_DIR`
- `PASSWORD_PDF_REPO_URL`
- `PASSWORD_PDF_REPO_REF`

## Update An Existing Install

On the target machine:

```bash
sudo /opt/password-pdf-generator/update.sh
```

That pulls the latest GitHub code, reinstalls Python dependencies if needed, preserves `/etc/password-pdf-generator/brand_settings.json` and `/etc/password-pdf-generator.env`, and restarts the service.

## Firewall Behavior

The installer configures `ufw` automatically:

- allows `OpenSSH`
- allows `80/tcp`
- allows `443/tcp`
- enables `ufw`

What it does not do automatically:

- router or CHR port forwarding
- public DNS records
- cloud firewall rules outside the VM

## Installed Runtime Paths

After installation, the important Linux paths are:

- code: `/opt/password-pdf-generator`
- venv: `/opt/password-pdf-generator/.venv`
- runtime config: `/etc/password-pdf-generator/brand_settings.json`
- secrets: `/etc/password-pdf-generator.env`
- install metadata: `/etc/password-pdf-generator/install-meta.env`
- service: `/etc/systemd/system/password-pdf-generator.service`
- Caddy site: `/etc/caddy/conf.d/password-pdf-generator.caddy`
- output and logs: `/var/lib/password-pdf-generator/output/pdf/wifi`
- path inventory file: `~/password-pdf-generator-paths.txt`

## App Entry Points

- API: `wifi_pdf.api:app`
- CLI: `python -m wifi_pdf.cli`
- Health endpoint: `GET /health`
- Webhook endpoint: `POST /webhooks/zoho/wifi-pdfs`

## Docs

- package details: [wifi_pdf/README.md](./wifi_pdf/README.md)
- Ubuntu/ESXi deployment notes: [docs/wifi-pdf-ubuntu-esxi.md](./docs/wifi-pdf-ubuntu-esxi.md)
