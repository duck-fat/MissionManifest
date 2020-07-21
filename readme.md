Manifests are cached on each call to `?manifest`. Caches are cleared the day after any `MISSION_DATE` specified with a `!manifest` command, or 14 days after the most recent `?manifest` on the caches `MISSION_NAME`.

# Commands:
* `?manifest "MISSION_NAME" TRACKING_CHANNEL`
 * Scan the specified channel for any responses that begin with `MISSION_NAME` made by a member with the "Player" role  and reply with the count and a link to each such response.
 * `MISSION_NAME` should be quoted if it contains spaces.
 * *Available to all server members.*
* `!manifest "MISSION_NAME" MISSION_DATE`
 * Start a cache for the MISSION_NAME manifest; cache will expire the day following MISSION_DATE.
 * *Available to "Admin" or "DM" roles only.*
