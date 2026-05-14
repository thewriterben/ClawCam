#pragma once

/*
 * clawcam_mqtt — MQTT transport for ClawCam nodes.
 *
 * On each wake cycle (when gateway upload is enabled):
 *   1. Connect to the configured MQTT broker.
 *   2. Subscribe to clawcam/{device_id}/commands (QoS 1).
 *   3. Publish event JSON to clawcam/{device_id}/events (QoS 1).
 *   4. Publish health JSON to clawcam/{device_id}/health (QoS 0).
 *   5. Wait briefly for any incoming command messages.
 *   6. Disconnect cleanly before deep sleep.
 *
 * Command messages received via MQTT are dispatched through
 * clawcam_command_client's handler functions — same execution path as HTTP polling.
 *
 * Configuration comes from Kconfig (sdkconfig):
 *   CONFIG_CLAWCAM_MQTT_BROKER_URL  — e.g. "mqtt://192.168.1.100"
 *   CONFIG_CLAWCAM_MQTT_PORT        — default 1883
 *   CONFIG_CLAWCAM_MQTT_KEEPALIVE   — seconds, default 15
 *   CONFIG_CLAWCAM_MQTT_QOS_EVENTS  — QoS for event publish, default 1
 */

#include <stdbool.h>
#include "esp_err.h"
#include "clawcam_config.h"

#ifdef __cplusplus
extern "C" {
#endif

#ifndef CONFIG_CLAWCAM_MQTT_BROKER_URL
#define CONFIG_CLAWCAM_MQTT_BROKER_URL "mqtt://localhost"
#endif

#ifndef CONFIG_CLAWCAM_MQTT_PORT
#define CONFIG_CLAWCAM_MQTT_PORT 1883
#endif

#ifndef CONFIG_CLAWCAM_MQTT_KEEPALIVE
#define CONFIG_CLAWCAM_MQTT_KEEPALIVE 15
#endif

#ifndef CONFIG_CLAWCAM_MQTT_QOS_EVENTS
#define CONFIG_CLAWCAM_MQTT_QOS_EVENTS 1
#endif

/* Topic naming — must match the gateway bridge conventions */
#define CLAWCAM_MQTT_ROOT           "clawcam"
#define CLAWCAM_MQTT_TOPIC_EVENTS   CLAWCAM_MQTT_ROOT "/%s/events"
#define CLAWCAM_MQTT_TOPIC_HEALTH   CLAWCAM_MQTT_ROOT "/%s/health"
#define CLAWCAM_MQTT_TOPIC_COMMANDS CLAWCAM_MQTT_ROOT "/%s/commands"
#define CLAWCAM_MQTT_TOPIC_ACK      CLAWCAM_MQTT_ROOT "/%s/ack"

/* Maximum time to wait for incoming commands after subscribing (ms) */
#define CLAWCAM_MQTT_COMMAND_WAIT_MS 3000

typedef struct {
    const char *broker_url;    /* e.g. "mqtt://192.168.1.100" */
    int         port;
    int         keepalive_s;
    const char *device_id;
    const char *username;      /* NULL if no auth */
    const char *password;      /* NULL if no auth */
} clawcam_mqtt_config_t;

/*
 * Callback invoked for each command received via MQTT.
 * command_type: "capture_now" | "apply_config_patch"
 * command_json: full command object JSON string
 */
typedef void (*clawcam_mqtt_command_cb_t)(const char *command_id,
                                          const char *command_type,
                                          const char *command_json);

/*
 * Publish an event to clawcam/{device_id}/events.
 * Connects, publishes, waits for any queued commands, then disconnects.
 * Returns ESP_OK if published successfully.
 */
esp_err_t clawcam_mqtt_publish_event(const clawcam_mqtt_config_t *cfg,
                                     const char *event_json,
                                     clawcam_mqtt_command_cb_t command_cb,
                                     clawcam_config_t *node_config);

/*
 * Publish a health report to clawcam/{device_id}/health (QoS 0, fire-and-forget).
 * Must be called after clawcam_mqtt_publish_event (reuses connection) or standalone.
 */
esp_err_t clawcam_mqtt_publish_health(const clawcam_mqtt_config_t *cfg,
                                      const char *health_json);

/*
 * Fill *cfg with factory defaults from Kconfig.
 * device_id must be set by the caller.
 */
void clawcam_mqtt_default_config(clawcam_mqtt_config_t *cfg, const char *device_id);

#ifdef __cplusplus
}
#endif
