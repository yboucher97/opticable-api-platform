# Google Admin Control Plane

## Goal

Give the Opticable automation platform direct, durable control over the Google configuration APIs that are not exposed by the existing analytics/connectors.

Existing Gmail, Calendar, Drive, Google Ads, Business Profile, GA4 reporting and Search Console connections remain separate. This integration is intentionally scoped to:

- Google Tag Manager configuration
- Google Analytics Admin configuration

## OAuth callback

Create a Google OAuth 2.0 **Web application** client with this authorized redirect URI:

`https://api01.opticable.ca/v1/integrations/google/oauth/callback`

The platform uses offline authorization and stores the refresh token on the VM at the configured `GOOGLE_OAUTH_CREDENTIALS_PATH`.

Never commit the client secret or refresh token to Git.

## Requested scopes

### Google Analytics Admin

- `https://www.googleapis.com/auth/analytics.edit`
- `https://www.googleapis.com/auth/analytics.readonly`

The Admin API can manage resources such as data streams, key events, event rules, custom dimensions, custom metrics, retention settings, measurement-protocol secrets and other property configuration supported by the API.

### Google Tag Manager

- `https://www.googleapis.com/auth/tagmanager.readonly`
- `https://www.googleapis.com/auth/tagmanager.edit.containers`
- `https://www.googleapis.com/auth/tagmanager.delete.containers`
- `https://www.googleapis.com/auth/tagmanager.edit.containerversions`
- `https://www.googleapis.com/auth/tagmanager.publish`
- `https://www.googleapis.com/auth/tagmanager.manage.accounts`
- `https://www.googleapis.com/auth/tagmanager.manage.users`

This supports accounts, containers, workspaces, tags, triggers, variables, folders, templates, versions, publishing, environments and permissions according to the current GTM API.

## Platform endpoints

OAuth:

- `GET /v1/integrations/google/oauth/status`
- `GET /v1/integrations/google/oauth/start`
- `GET /v1/integrations/google/oauth/callback`

Controlled provider gateway:

- `/v1/google/tagmanager/{resource_path}`
- `/v1/google/analytics_admin_v1beta/{resource_path}`
- `/v1/google/analytics_admin_v1alpha/{resource_path}`

Allowed methods:

- GET
- POST
- PUT
- PATCH
- DELETE

Every non-GET call requires:

`X-Change-Reason: <human-readable reason>`

and is written to the automation audit log.

All gateway endpoints require the existing `X-API-Key`.

## Automation actions

The provider adapter registers:

- `google.gtm.request`
- `google.ga4_admin.request`

Example GTM read step:

```yaml
- id: list_gtm_accounts
  action: google.gtm.request
  with:
    method: GET
    path: accounts
```

Example GA4 Admin mutation:

```yaml
- id: create_key_event
  action: google.ga4_admin.request
  with:
    method: POST
    version: v1beta
    path: properties/123456789/keyEvents
    reason: Create lead-submission key event from approved tracking desired state
    body:
      eventName: generate_lead
```

Provider mutations require a reason and are audit logged.

## Safe GTM release pattern

Do not edit the live container blindly.

The preferred workflow is:

1. discover account/container
2. create or choose a dedicated workspace
3. create/update tags, triggers and variables
4. inspect workspace status
5. quick-preview/validate
6. create a container version
7. verify no compiler errors
8. publish the version
9. record the published version ID in audit history

This creates a rollback point through previous container versions.

## Required one-time Google Cloud setup

1. Select or create the Google Cloud project owned by Opticable.
2. Enable **Tag Manager API**.
3. Enable **Google Analytics Admin API**.
4. Configure the OAuth consent screen.
5. Create an OAuth 2.0 Web application client.
6. Add the exact callback URL above.
7. Put the client ID and client secret in the VM environment file; do not commit them.
8. Open the platform Google OAuth start route and approve access once.
9. Verify `/v1/integrations/google/oauth/status`.
10. Run read-only discovery before any mutation.

## Upgrade/portability model

Google provider behavior lives behind the provider adapter. Workflow definitions reference stable action names rather than HTTP hosts.

If Google changes API versions:

- update the adapter
- keep workflow contracts stable where possible
- run CI
- test against a workspace/non-destructive read
- deploy
- migrate version-specific workflow inputs only when necessary
