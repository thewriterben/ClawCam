#include "clawcam_mqtt.h"

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

/* Optional MQTT client — gated identically to HTTP */
#if defined(__has_include)
#  if __has_include("mqtt_client.h")
#    include "mqtt_client.h"
#    define CLAWCAM_HAVE_MQTT_CLIENT 1
#  else
#    define CLAWCAM_HAVE_MQTT_CLIENT 0
#  endif
#else
#  define CLAWCAM_HAVE_MQTT_CLIENT 0
#endif

#ifndef CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED
#define CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED 0
#endif

static const char *TAG = "clawcam_mqtt";

#define MQTT_CONNECTED_BIT  BIT0
#define MQTT_PUBLISHED_BIT  BIT1
#define MQTT_TIMEOUT_MS     8000

/* ── Topic helpers ──────────────────────────────────────────────────────── */

static void make_topic(char *buf, size_t buf_len, const char *fmt, const char *device_id)
{
    snprintf(buf, buf_len, fmt, device_id);
}

/* ── Default config ─────────────────────────────────────────────────────── */

void clawcam_mqtt_default_config(clawcam_mqtt_config_t *cfg, const char *device_id)
{
    cfg->broker_url  = CONFIG_CLAWCAM_MQTT_BROKER_URL;
    cfg->port        = CONFIG_CLAWCAM_MQTT_PORT;
    cfg->keepalive_s = CONFIG_CLAWCAM_MQTT_KEEPALIVE;
    cfg->device_id   = device_id;
    cfg->username    = NULL;
    cfg->password    = NULL;
}

/* ── Tiny JSON helpers (shared with command_client) ─────────────────────── */

static void json_extract_str_local(const char *json, const char *key, char *buf, size_t buf_len)
{
    if (!json || !key) { buf[0] = '\0'; return; }
    char search[80];
    snprintf(search, sizeof(search), "\"%s\"", key);
    const char *p = strstr(json, search);
    if (!p) { buf[0] = '\0'; return; }
    p += strlen(search);
    while (*p == ' ' || *p == ':' || *p == '\t') p++;
    if (*p != '"') { buf[0] = '\0'; return; }
    p++;
    size_t i = 0;
    while (*p && *p != '"' && i < buf_len - 1) {
        if (*p == '\\') p++;
        buf[i++] = *p++;
    }
    buf[i] = '\0';
}

/* ── Real MQTT implementation ───────────────────────────────────────────── */

#if CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED && CLAWCAM_HAVE_MQTT_CLIENT

typedef struct {
    EventGroupHandle_t          events;
    clawcam_mqtt_command_cb_t   command_cb;
    clawcam_config_t           *node_config;
    const char                 *device_id;
    char                        cmd_topic[128];
    int                         commands_received;
} mqtt_ctx_t;

static void mqtt_event_handler(void *arg, esp_event_base_t base, int32_t event_id, void *event_data)
{
    mqtt_ctx_t *ctx = (mqtt_ctx_t *)arg;
    esp_mqtt_event_handle_t event = (esp_mqtt_event_handle_t)event_data;

    switch ((esp_mqtt_event_id_t)event_id) {
    case MQTT_EVENT_CONNECTED:
        xEventGroupSetBits(ctx->events, MQTT_CONNECTED_BIT);
        break;

    case MQTT_EVENT_PUBLISHED:
        xEventGroupSetBits(ctx->events, MQTT_PUBLISHED_BIT);
        break;

    case MQTT_EVENT_DATA:
        /* Received a command from the gateway */
        if (ctx->command_cb == NULL) break;
        if (event->data_len <= 0 || event->data_len > 2048) break;

        char *cmd_buf = malloc(event->data_len + 1);
        if (!cmd_buf) break;
        memcpy(cmd_buf, event->data, event->data_len);
        cmd_buf[event->data_len] = '\0';

        char command_id[64];
        char command_type[48];
        json_extract_str_local(cmd_buf, "command_id",   command_id,   sizeof(command_id));
        json_extract_str_local(cmd_buf, "command_type", command_type, sizeof(command_type));

        if (command_id[0] && command_type[0]) {
            ESP_LOGI(TAG, "received command via MQTT: id=%s type=%s", command_id, command_type);
            ctx->command_cb(command_id, command_type, cmd_buf);
            ctx->commands_received++;
        }
        free(cmd_buf);
        break;

    case MQTT_EVENT_ERROR:
        ESP_LOGW(TAG, "MQTT error; check broker connectivity");
        break;

    default:
        break;
    }
}

static esp_mqtt_client_handle_t create_client(const clawcam_mqtt_config_t *cfg, mqtt_ctx_t *ctx)
{
    char broker_uri[256];
    snprintf(broker_uri, sizeof(broker_uri), "%s:%d", cfg->broker_url, cfg->port);

    esp_mqtt_client_config_t mqtt_cfg = {
        .broker.address.uri       = broker_uri,
        .session.keepalive        = cfg->keepalive_s,
        .credentials.username     = cfg->username,
        .credentials.authentication.password = cfg->password,
    };

    esp_mqtt_client_handle_t client = esp_mqtt_client_init(&mqtt_cfg);
    if (!client) return NULL;
    esp_mqtt_client_register_event(client, ESP_EVENT_ANY_ID, mqtt_event_handler, ctx);
    return client;
}

esp_err_t clawcam_mqtt_publish_event(const clawcam_mqtt_config_t *cfg,
                                     const char *event_json,
                                     clawcam_mqtt_command_cb_t command_cb,
                                     clawcam_config_t *node_config)
{
    mqtt_ctx_t ctx = {
        .events            = xEventGroupCreate(),
        .command_cb        = command_cb,
        .node_config       = node_config,
        .device_id         = cfg->device_id,
        .commands_received = 0,
    };
    make_topic(ctx.cmd_topic, sizeof(ctx.cmd_topic),
               CLAWCAM_MQTT_TOPIC_COMMANDS, cfg->device_id);

    esp_mqtt_client_handle_t client = create_client(cfg, &ctx);
    if (!client) { vEventGroupDelete(ctx.events); return ESP_FAIL; }

    esp_mqtt_client_start(client);

    /* Wait for connection */
    EventBits_t bits = xEventGroupWaitBits(ctx.events, MQTT_CONNECTED_BIT,
                                           pdFALSE, pdFALSE,
                                           pdMS_TO_TICKS(MQTT_TIMEOUT_MS));
    if (!(bits & MQTT_CONNECTED_BIT)) {
        ESP_LOGW(TAG, "MQTT connect timeout; skipping publish");
        esp_mqtt_client_stop(client);
        esp_mqtt_client_destroy(client);
        vEventGroupDelete(ctx.events);
        return ESP_ERR_TIMEOUT;
    }

    /* Subscribe to commands topic before publishing */
    esp_mqtt_client_subscribe(client, ctx.cmd_topic, 1);

    /* Publish the event */
    char events_topic[128];
    make_topic(events_topic, sizeof(events_topic), CLAWCAM_MQTT_TOPIC_EVENTS, cfg->device_id);
    int msg_id = esp_mqtt_client_publish(client, events_topic, event_json, 0,
                                          CONFIG_CLAWCAM_MQTT_QOS_EVENTS, 0);
    if (msg_id < 0) {
        ESP_LOGW(TAG, "event publish failed");
    } else {
        ESP_LOGI(TAG, "event published to %s (msg_id=%d)", events_topic, msg_id);
        /* Wait for PUBACk if QoS 1 */
        if (CONFIG_CLAWCAM_MQTT_QOS_EVENTS >= 1) {
            xEventGroupWaitBits(ctx.events, MQTT_PUBLISHED_BIT,
                                pdFALSE, pdFALSE, pdMS_TO_TICKS(4000));
        }
    }

    /* Wait briefly for incoming commands */
    vTaskDelay(pdMS_TO_TICKS(CLAWCAM_MQTT_COMMAND_WAIT_MS));
    ESP_LOGI(TAG, "received %d command(s) via MQTT this wake cycle", ctx.commands_received);

    esp_mqtt_client_stop(client);
    esp_mqtt_client_destroy(client);
    vEventGroupDelete(ctx.events);
    return ESP_OK;
}

esp_err_t clawcam_mqtt_publish_health(const clawcam_mqtt_config_t *cfg,
                                      const char *health_json)
{
    /* Standalone health publish: connect, fire-and-forget, disconnect */
    mqtt_ctx_t ctx = {
        .events            = xEventGroupCreate(),
        .command_cb        = NULL,
        .node_config       = NULL,
        .device_id         = cfg->device_id,
        .commands_received = 0,
    };

    esp_mqtt_client_handle_t client = create_client(cfg, &ctx);
    if (!client) { vEventGroupDelete(ctx.events); return ESP_FAIL; }

    esp_mqtt_client_start(client);
    EventBits_t bits = xEventGroupWaitBits(ctx.events, MQTT_CONNECTED_BIT,
                                           pdFALSE, pdFALSE,
                                           pdMS_TO_TICKS(MQTT_TIMEOUT_MS));
    if (!(bits & MQTT_CONNECTED_BIT)) {
        esp_mqtt_client_stop(client);
        esp_mqtt_client_destroy(client);
        vEventGroupDelete(ctx.events);
        return ESP_ERR_TIMEOUT;
    }

    char health_topic[128];
    make_topic(health_topic, sizeof(health_topic), CLAWCAM_MQTT_TOPIC_HEALTH, cfg->device_id);
    esp_mqtt_client_publish(client, health_topic, health_json, 0, 0, 0); /* QoS 0 */
    vTaskDelay(pdMS_TO_TICKS(200)); /* brief flush window */

    esp_mqtt_client_stop(client);
    esp_mqtt_client_destroy(client);
    vEventGroupDelete(ctx.events);
    return ESP_OK;
}

#else /* stub mode */

esp_err_t clawcam_mqtt_publish_event(const clawcam_mqtt_config_t *cfg,
                                     const char *event_json,
                                     clawcam_mqtt_command_cb_t command_cb,
                                     clawcam_config_t *node_config)
{
    (void)event_json; (void)command_cb; (void)node_config;
    char topic[128];
    make_topic(topic, sizeof(topic), CLAWCAM_MQTT_TOPIC_EVENTS, cfg->device_id);
    ESP_LOGI(TAG, "MQTT stub: would publish event to %s", topic);
    return ESP_OK;
}

esp_err_t clawcam_mqtt_publish_health(const clawcam_mqtt_config_t *cfg,
                                      const char *health_json)
{
    (void)health_json;
    char topic[128];
    make_topic(topic, sizeof(topic), CLAWCAM_MQTT_TOPIC_HEALTH, cfg->device_id);
    ESP_LOGI(TAG, "MQTT stub: would publish health to %s", topic);
    return ESP_OK;
}

#endif /* CONFIG_CLAWCAM_GATEWAY_UPLOAD_ENABLED && CLAWCAM_HAVE_MQTT_CLIENT */
