# Legacy archives

The predecessor-project zip snapshots that used to live here (28.6 MB —
effectively the repo's entire pack weight) are no longer tracked. Refer to
the source repositories instead:

| Archive | Source |
|---|---|
| `WildCAM_ESP32-main.zip` | https://github.com/thewriterben/WildCAM_ESP32 |
| `esp-claw-master.zip` | https://github.com/thewriterben/esp-claw |
| `Oh-Ben-Claw-main.zip` | https://github.com/thewriterben/Oh-Ben-Claw |

Local copies of the zips remain on disk (gitignored). Note: the blobs still
exist in git history; run `git filter-repo --path legacy_archives --invert-paths`
(and force-push) if you want the ~28 MB back from `.git`.
