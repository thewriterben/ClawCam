idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES
        clawcam_camera
        clawcam_capabilities
        clawcam_command_client
        clawcam_config
        clawcam_events
        clawcam_gateway_client
        clawcam_motion
        clawcam_mqtt
        clawcam_ota
        clawcam_power
        clawcam_storage
)
