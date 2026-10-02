> HISTORICAL — retained for past decisions/evidence; **do not use as current deployment or configuration instructions**. Current authority: [current guide](../../../../docs/OPTIBRAIN_CODEX_ONBOARDING.md).

# Linux VPS Deployment

This folder contains the Linux service assets for running `Omada Site Creator` unattended on an Ubuntu VM.

## What it installs

- code in `/opt/omada-site-creator`
- runtime data in `/var/lib/omada-site-creator/data`
- env file in `/etc/omada-site-creator.env`
- systemd unit in `/etc/systemd/system/omada-site-creator.service`
- optional Caddy site in `/etc/caddy/conf.d/omada-site-creator.caddy`

## Quick install

```bash
sudo OMADA_SITE_CREATOR_PUBLIC_HOST=omada.example.com \
  bash /opt/omada-site-creator/deploy/linux/install.sh
```

If you are installing from GitHub directly:

```bash
curl -fsSL https://raw.githubusercontent.com/yboucher97/Omada_Site_Creator/main/deploy/linux/install.sh \
  | sudo OMADA_SITE_CREATOR_PUBLIC_HOST=omada.example.com bash
```

## Required secrets

Edit `/etc/omada-site-creator.env` after install:

- `OMADA_SITE_CREATOR_WEBHOOK_TOKEN`
- `OMADA_SITE_CREATOR_CLOUD_EMAIL`
- `OMADA_SITE_CREATOR_CLOUD_PASSWORD`

Optional:

- `OMADA_SITE_CREATOR_DEVICE_USERNAME`
- `OMADA_SITE_CREATOR_DEVICE_PASSWORD`

## Same VM as Password_PDF_Generator

If `Password_PDF_Generator` is already on the box, keep it on its own hostname and give Omada a second hostname:

- `wifi-api.example.com` -> Password PDF Generator
- `omada.example.com` -> Omada Site Creator

Both services can run behind Caddy on the same VM without port conflicts because they listen on different localhost ports.
