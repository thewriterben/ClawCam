#pragma once

/*
 * clawcam_command_client — polls the gateway command queue on each wake cycle.
 *
 * Flow:
 *   1. GET /api/v1/commands/{device_id}/pending
 *   2. For each command, dispatch to the appropriate handler.
 *   3. POST /api/v1/commands/{command_id}/ack with status + result.
 *
 * Commands supported:
 *   "capture_now"       — trigger an immediate capture cycle.
 *   "apply_config_patch" — write config keys to NVS via clawcam_config.
 */

#include <stdbool.h>
#include "esp_err.h"
#include "clawcam_config.h"
#include "clawcam_gateway_client.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Callback invoked when the gateway queues a capture_now command.
 * The implementation in main.c runs run_capture_cycle("command"). */
typedef void (*clawcam_command_capture_cb_t)(const char *command_id, const char *reason);

/* Callback invoked when the gateway queues a firmware_update command.
 * Receives the full gateway base URL, the download path, and SHA256 hex string.
 * The implementation in main.c delegates to clawcam_ota_update().
 * Return ESP_OK on success; any other value causes the command to ack as "failed". */
typedef esp_err_t (*clawcam_command_ota_cb_t)(
    const char *base_url,
    const char *firmware_path,
    const char *sha256,
    const char *version);

typedef struct {
    const clawcam_gateway_client_config_t *gateway_config;
    const char *device_id;
    clawcam_config_t *node_config;          /* updated in-place by apply_config_patch */
    clawcam_command_capture_cb_t capture_cb; /* called for capture_now commands */
    clawcam_command_ota_cb_t ota_cb;        /* called for firmware_update commands; may be NULL */
    int max_commands_per_wake;              /* safety limit; 0 = use default (5) */
} clawcam_command_client_config_t;

/*
 * Poll the gateway for pending commands and execute them.
 * Returns the number of commands successfully handled (≥ 0) or a negative
 * esp_err_t value on a transport/fatal error.
 */
int clawcam_command_client_poll(const clawcam_command_client_config_t *config);

#ifdef __cplusplus
}
#endif
