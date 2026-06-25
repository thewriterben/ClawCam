# Phase 14 — Hardware Integration Field-Test Plan

**Status:** Planned · **Target:** Q3–Q4 2026 · **Prereq:** Phase 13 code-complete (gateway, MCP bridge, firmware components all green in simulation/CI)

This runbook takes ClawCam from a fully-simulated stack to a **physical ESP32-S3-EYE node**
running in the field. It validates, on real hardware, the three Phase 14 roadmap deliverables:
physical node deployment (PIR → capture → upload), MQTT on device, and OTA on device. Every
step maps to an acceptance criterion and to the firmware component / gateway endpoint that
already exists in the repo — Phase 14 adds **no new product surface area**, it proves the
existing one on metal.

---

## 1. Objective & scope

Prove that a battery-powered ESP32-S3-EYE node, flashed with the existing
`firmware/clawcam_node_espidf` image, performs the full deterministic loop in the field:

```
PIR wake → camera capture → store on SD → register/upload to gateway →
poll & ack commands → (MQTT real-time) → deep sleep → repeat,
with OTA firmware update on demand.
```

In scope: one node + one gateway on the same LAN, then a 24–72 h unattended soak.
Out of scope: multi-node mesh, LoRa backhaul, solar charging characterization (tracked separately).

---

## 2. Bill of materials

| Item | Notes |
|------|-------|
| ESP32-S3-EYE dev board (v2.2) | OV2640 camera, 8 MB PSRAM; board profile `boards/esp32_s3_eye_v22.json` |
| PIR sensor (e.g. AM312/HC-SR501) | Wired to the EXT0 wake GPIO defined in `clawcam_config` |
| microSD card (FAT32, ≥8 GB) | Primary media + event store (`cap_clawcam_storage`) |
| LiPo battery + fuel gauge | For `cap_clawcam_power` battery-aware sleep + longevity test |
| USB-C cable / UART adapter | Flashing + serial console |
| Gateway host | Laptop/Pi on same LAN running `clawcam_gateway` |
| (Optional) MQTT broker | Mosquitto/EMQX for the real-time phase |
| Weatherproof enclosure | Field soak only |
| USB power meter or multimeter | Sleep/active current measurement |

---

## 3. Pre-flight

1. **Build & flash** per `firmware/clawcam_node_espidf/BUILD_ESP32_S3_EYE.md`, using
   `sdkconfig.defaults.esp32s3_eye`. Confirm camera, PSRAM, and SD are enabled in `menuconfig`.
2. **Provision NVS config** (`clawcam_config`): `gateway_base_url`, `device_id`, `deployment_id`,
   `capture_interval_s`, `low_battery_sleep_s`. Set `CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED=y`.
3. **Start the gateway**: `python -m clawcam_gateway.main` (or docker-compose). Confirm
   `GET /api/v1/health` and the dashboard load. Note the LAN URL.
4. **(Auth)** If auth is enabled, mint a write-scoped API key and load it into NVS.
5. **Baseline serial log**: capture a clean boot to confirm component init order
   (config → camera → storage → command client → mqtt/ota stubs).

---

## 4. Test phases & acceptance criteria

### Phase A — Bench bring-up
- **Do:** Power the board on USB. Watch the serial console through one full wake cycle.
- **Pass:** Board boots, camera initializes (OV2640 detected), SD mounts, a smoke-test capture
  is written to SD, node enters deep sleep at the configured interval. No panics/brownouts.

### Phase B — PIR trigger → capture → SD
- **Do:** Trigger the PIR (wave a hand). Repeat 10×.
- **Pass:** Each EXT0 wake produces exactly one JPEG + event record on SD; timer-fallback wake
  also fires when idle. Capture latency from trigger logged.

### Phase C — Gateway upload (HTTP)
- **Do:** With `gateway_base_url` set, let the node register and upload.
- **Pass:** Device appears via `GET /api/v1/devices/{id}` declaring the canonical
  `cap_clawcam_*` capabilities; events land via the ingest path and are visible on `/dashboard`;
  inference results populate for uploaded media. **SD remains source of truth** if upload fails.

### Phase D — Command loop (capture_now / apply_config_patch)
- **Do:** From the brain (or `POST` the gated tool with approval), queue `capture_now`.
- **Pass:** Node polls `GET /api/v1/commands/{id}/pending`, executes, and acks via
  `POST /api/v1/commands/{cmd}/ack` with `executed`. `apply_config_patch` updates NVS live
  (verified by changed `capture_interval_s` on next cycle). Capability gate rejects commands
  the device does not declare.

### Phase E — MQTT real-time (optional but targeted)
- **Do:** Start the broker, set `CLAWCAM_MQTT_ENABLED=true` on the gateway and enable the
  `clawcam_mqtt` path on the node.
- **Pass:** Node publishes events to `clawcam/{id}/events`; a `capture_now` queued on the gateway
  is pushed to `clawcam/{id}/commands` (QoS 1) and executed without waiting for the next poll.
  Node falls back to HTTP cleanly when the broker is unreachable.

### Phase F — OTA on device
- **Do:** `POST /api/v1/firmware` a new signed `.bin`; queue `queue_firmware_update` (gated).
- **Pass:** Node downloads via streaming HTTP, **verifies SHA256**, writes the OTA partition,
  sets boot partition, reboots into the new build, and acks `executed`. A corrupted/short
  download is rejected (SHA mismatch) and the running partition is preserved.

### Phase G — Deep sleep & power
- **Do:** Measure current in deep sleep and during an active capture cycle. Force a low-battery
  reading.
- **Pass:** Deep-sleep current within board target; EXT0 PIR wake + timer fallback both work;
  low battery triggers extended `low_battery_sleep_s` from NVS. Record mA figures.

### Phase H — Field soak (24–72 h)
- **Do:** Deploy in enclosure outdoors on battery. Leave unattended.
- **Pass:** Continuous operation for the soak window; capture cadence matches config; no SD
  corruption; battery longevity ≥ target; gateway shows a continuous event/health stream with
  no unexplained gaps.

---

## 5. Data to record

- Per-phase pass/fail + serial logs.
- Capture latency (PIR edge → JPEG written) distribution.
- Upload success rate and retry behavior under flaky Wi-Fi.
- Deep-sleep and active current (mA); estimated battery days.
- OTA total time and verification result.
- Soak: event count, health-report interval jitter, battery curve.

---

## 6. Troubleshooting & rollback

- **No capture on PIR:** verify EXT0 GPIO + PIR Vcc; check `clawcam_config` wake pin; confirm
  not in low-battery extended sleep.
- **Upload fails:** confirm LAN URL/API key; node should keep events on SD and retry — verify
  no data loss.
- **OTA fails / boot loop:** ESP-IDF rollback to the previous OTA partition; re-flash over UART
  as last resort. Never delete the factory partition.
- **Brownout under camera load:** use a stronger supply/battery; the camera + Wi-Fi current
  spike is the usual culprit.

---

## 7. Exit criteria (Phase 14 done)

Phases A–D and F pass on hardware (core loop + OTA), Phase G meets the power target, and a
≥24 h soak (Phase H) completes with no data loss. MQTT (Phase E) passes if a broker is in scope.
On completion, update `docs/STATUS.md` and `docs/ROADMAP.md` to mark Phase 14 complete and record
the measured power/longevity numbers.
