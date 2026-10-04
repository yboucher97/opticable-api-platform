# Source health

AUTHORITATIVE CURRENT. Authentication, accepted API requests, source freshness and business/event coverage are distinct. Connected does not mean collecting.

GA4 uses one fixed90-day production-host date/event/host report, per-site event dates and a separate auth state. FRESH means a positive observed production event date within3 Toronto calendar days. NO RECENT DATA requests tag/consent/coverage verification and never asserts zero visitors. Failed refreshes preserve prior observations and show the failure separately. Realtime restoration proof and standard-report propagation are recorded independently. Overall freshness never hides a missing site's status.

Acquisition refresh remains14 fixed Google read requests/40seconds at most, daily, with isolated failure and dated cache preservation. No new provider write or timer is introduced. Permit caches refresh at most daily; tender proofs are bounded manual/current-source observations and expire after72hours. A stale/closed/unresolved target is withheld from Sales while retained in Acquisition research. Existing source health also distinguishes WORKING, PARTIAL, BLOCKED, RATE LIMITED, PLAN LIMITED, AUTH EXPIRED and UNKNOWN, with separate stale flags. Optional provider failure cannot disable lifecycle or Mail families.
