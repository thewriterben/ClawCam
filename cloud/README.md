# ClawCam Cloud

Cloud *services* (this directory) are optional and intentionally deferred until the local node and gateway vertical slice is working.

Not to be confused with the cloud **upload backend**, which is real and shipped: the root README's "Cloud Backend: Working" refers to the gateway's media sync (`gateway/clawcam_gateway/sync/` — S3/GCS/Noop stores, auto-upload with retry tracking, disabled by default). That is a gateway feature; nothing in this directory implements it.

Future cloud work may include authenticated project dashboards, multi-user review, long-term object storage, collaboration, standards-aware exports, and integration with biodiversity data platforms.

The local gateway remains the first-class field deployment unit and must continue operating when cloud connectivity is unavailable.
