# ClawCam Roadmap

The ClawCam roadmap is intentionally phased. Each phase must produce a working, testable increment before proceeding to the next milestone.

## Phase 0: Repository Foundation (100% Complete)
| Deliverable             | Acceptance Criteria                                                                                            | Completion Status |
|-------------------------|----------------------------------------------------------------------------------------------------------------|--------------------|
| Monorepo skeleton       | Active source tree exists outside `legacy_archives/`.                                                        | ✅ Completed       |
| Status documentation    | `docs/STATUS.md` clearly separates working, scaffolded, framework, planned, and legacy-reference areas.       | ✅ Completed       |
| Architecture documentation | `docs/ARCHITECTURE.md` defines node, gateway, brain, and cloud responsibilities.                          | ✅ Completed       |
| Initial schemas         | Device, event, observation, and health schemas exist and are validated by tests.                              | ✅ Completed       |
| CI                      | Basic schema validation and Python test workflow exists.                                                     | ✅ Completed       |

## Phase 1: Working Vertical Slice (In Progress, 50%)
| Deliverable             | Acceptance Criteria                                                                                            | Completion Status |
|-------------------------|----------------------------------------------------------------------------------------------------------------|--------------------|
| Node or simulator event | A valid event payload can be produced and submitted.                                                           | 🔄 In Progress     |
| Gateway ingest          | Gateway validates and persists events.                                                                        | 🔄 In Progress     |
| Local API               | Recent events and node health can be queried.                                                                 | 🔄 In Progress     |
| Brain tool              | A simple agent-compatible tool can query recent detections.                                                   | 🔲 Planned         |
| Documentation           | Setup steps reproduce the flow locally.                                                                       | 🔲 Planned         |

## Detailed Timeline
- **Phase 1 Expected Completion**: End of Q2 2026
- **Phase 2 Expected Start**: Early Q3 2026

Future phases (Details intentionally deferred until Phase 1 completes execution):
- **Phase 2**: ESP-Claw native node functionality.
- **Phase 3**: Incorporation of AI inference models.

---