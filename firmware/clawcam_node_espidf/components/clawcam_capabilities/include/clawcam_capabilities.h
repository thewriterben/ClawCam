#pragma once

/*
 * ClawCam ESP-Claw capability group identifiers.
 *
 * A node includes the strings it supports in its device registration payload
 * under the "capabilities" array. The gateway and brain use this list to
 * decide which operations are safe to queue for a given node.
 *
 * Usage (device registration JSON fragment):
 *   "capabilities": [
 *     "cap_clawcam_camera_trap",
 *     "cap_clawcam_power",
 *     "cap_clawcam_storage",
 *     "cap_clawcam_events"
 *   ]
 */

/* Core wildlife capture capability: PIR trigger, manual capture, camera status */
#define CLAWCAM_CAP_CAMERA_TRAP   "cap_clawcam_camera_trap"

/* Battery/solar state, power profile read and limited write */
#define CLAWCAM_CAP_POWER         "cap_clawcam_power"

/* Storage health, media listing, free-space query */
#define CLAWCAM_CAP_STORAGE       "cap_clawcam_storage"

/* Environment, GPS, light, and optional external sensor readings */
#define CLAWCAM_CAP_SENSORS       "cap_clawcam_sensors"

/* Publish wildlife events, health events, and maintenance events */
#define CLAWCAM_CAP_EVENTS        "cap_clawcam_events"

/*
 * Capability set string for the ESP32-S3-EYE reference board.
 * Use this as the "capabilities" array value in device registration JSON.
 */
#define CLAWCAM_ESP32_S3_EYE_CAPABILITIES \
    "\"" CLAWCAM_CAP_CAMERA_TRAP "\"," \
    "\"" CLAWCAM_CAP_POWER "\"," \
    "\"" CLAWCAM_CAP_STORAGE "\"," \
    "\"" CLAWCAM_CAP_EVENTS "\""
