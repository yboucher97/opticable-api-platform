# OptiBrain Phase 2A R2 discovery

Phase 2A uses the root-only bootstrap credential at
`/etc/optibrain/cloudflare-test-token`. It is an account-owned Cloudflare API
token and must be verified with:

`GET /accounts/{CLOUDFLARE_ACCOUNT_ID}/tokens/verify`

The production `CLOUDFLARE_API_TOKEN` in `/etc/opticable-workflow-api.env` is
not changed or used as the bootstrap credential. User-owned tokens use
`GET /user/tokens/verify`; account-owned tokens must not be tested solely
through that endpoint. The earlier 401 was a credential-type/tooling discovery,
not proof that the bootstrap token was invalid.

The root-only discovery script performs only GET requests: account-token
verification, account identity, R2 bucket listing, target-bucket existence,
and token-policy inspection. It does not call `POST /accounts/{id}/r2/buckets`.
R2 bucket creation requires the `Workers R2 Storage Write` permission; the
script reports that permission when the token-details response exposes it and
otherwise reports the capability as insufficient or undetermined.

The bootstrap token is temporary/bootstrap-only. After the dedicated bucket is
created in a separately authorized step, routine backup access must be narrowed
to `optibrain-recovery-prod` as far as Cloudflare permits. The routine uploader
must never receive the offline AGE private/decryption key.

## Verified resume, 2026-09-27

Discovery now parses `result.buckets` and rejects malformed responses instead of
misreporting absence. Runtime health failures return nonzero. The target bucket
exists; managed public access is disabled and no custom domains are configured.
The account bootstrap policy includes Account API Tokens Read/Write, so creation
of a dedicated token was possible through the API without a dashboard boundary.
See the off-host recovery document for the verified scope and implementation.
