#include "clawcam_events.h"

#include <stdio.h>
#include "esp_log.h"

static const char *TAG = "clawcam_events";

static const char *safe_str(const char *value, const char *fallback)
{
    return value ? value : fallback;
}

static int write_nullable_string(char *buffer, size_t buffer_len, const char *value)
{
    if (value == NULL) {
        return snprintf(buffer, buffer_len, "null");
    }
    return snprintf(buffer, buffer_len, "\"%s\"", value);
}

esp_err_t clawcam_event_build_capture_json(const clawcam_event_capture_t *event, char *out_json, size_t out_json_len)
{
    if (event == NULL || out_json == NULL || out_json_len == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    if (event->event_id == NULL || event->device_id == NULL || event->timestamp == NULL || event->media_id == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    char deployment_json[96];
    int deployment_written = write_nullable_string(deployment_json, sizeof(deployment_json), event->deployment_id);
    if (deployment_written < 0 || (size_t)deployment_written >= sizeof(deployment_json)) {
        return ESP_ERR_INVALID_SIZE;
    }

    int written = snprintf(
        out_json,
        out_json_len,
        "{"
        "\"event_id\":\"%s\"," 
        "\"event_type\":\"%s\"," 
        "\"device_id\":\"%s\"," 
        "\"deployment_id\":%s," 
        "\"timestamp\":\"%s\"," 
        "\"time_source\":\"%s\"," 
        "\"source\":\"node\"," 
        "\"media\":[{"
        "\"media_id\":\"%s\"," 
        "\"media_type\":\"image\"," 
        "\"path\":\"%s\"," 
        "\"uri\":null," 
        "\"mime_type\":\"%s\"," 
        "\"size_bytes\":%u," 
        "\"sha256\":null"
        "}],"
        "\"classifications\":[{"
        "\"classification_id\":\"cls-%s-smoke\"," 
        "\"label\":\"unclassified\"," 
        "\"scientific_name\":null," 
        "\"taxon_id\":null," 
        "\"confidence\":null," 
        "\"source\":\"node\"," 
        "\"review_state\":\"unreviewed\""
        "}],"
        "\"metadata\":{"
        "\"trigger\":\"%s\"," 
        "\"capture_profile\":\"%s\"," 
        "\"board_profile\":\"%s\"," 
        "\"width\":%lu," 
        "\"height\":%lu," 
        "\"firmware_generated\":true"
        "}"
        "}\n",
        event->event_id,
        safe_str(event->event_type, "capture"),
        event->device_id,
        deployment_json,
        event->timestamp,
        safe_str(event->time_source, "unknown"),
        event->media_id,
        safe_str(event->media_path, ""),
        safe_str(event->mime_type, "image/jpeg"),
        (unsigned)event->size_bytes,
        event->event_id,
        safe_str(event->trigger, "camera_smoke_test"),
        safe_str(event->capture_profile, "smoke_test"),
        safe_str(event->board_profile, "unknown"),
        (unsigned long)event->width,
        (unsigned long)event->height);

    if (written < 0 || (size_t)written >= out_json_len) {
        ESP_LOGE(TAG, "event JSON buffer too small for event %s", event->event_id);
        return ESP_ERR_INVALID_SIZE;
    }
    return ESP_OK;
}
