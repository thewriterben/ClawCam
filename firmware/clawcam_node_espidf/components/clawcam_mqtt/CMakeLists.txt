idf_component_register(
    SRCS "clawcam_mqtt.c"
    INCLUDE_DIRS "include"
    REQUIRES clawcam_config mqtt freertos
)
