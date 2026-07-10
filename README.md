# Automower Supervisor v0.5.12

Automower Supervisor is a local Home Assistant custom integration that aggregates and monitors Husqvarna Automower / Robonect installations. It tracks the health and errors of 11 specific robotic lawn mowers, ensuring that any real errors detected are persistently stored and tracked until verified.

## Improvements in version 0.5.12

- **Robonect Stale Error-Code Clear**: Adds conservative handling for cases where Robonect keeps a stale non-zero `mower_error_code` even though the mower appears healthy and the binary error sensor is off.
- **Error Code Entity Tracking**: Supervisor now tracks `sensor.<robot>_mower_error_code` in addition to Robonect's error message and binary error sensor.
- **Code 0 Wins Over Stale Text**: If Robonect reports error code `0` and binary error is off, stale error text like `Battery empty` no longer keeps the robot in `ACTIVE_ERROR`.
- **Reset → AUTO Verification**: For clear stale-code evidence, Supervisor sends `error_reset`, waits 15 seconds, sends `auto`, waits 60 seconds, and re-checks the error code.
- **One Reboot Fallback**: If the code is still non-zero, Supervisor sends `reboot` once, waits 60 seconds, sends `auto`, waits 40 seconds, and verifies again.
- **Safety Gates**: The stale-code clear flow only runs for fresh, online, resting, non-mowing robots with binary error off and strong stale-error evidence.
- **Diagnostics**: Individual robot sensors expose `current_error_code`, stale-code fix stage/result, incident, and timestamps.
- **Regression Coverage**: Adds tests for error-code entity discovery, code-0 stale text clearing, stale-code eligibility, and reboot button mapping.

## Improvements in version 0.5.11

- **Recovery Mowing in Progress**: A robot with a cleared-but-unverified error that is currently mowing is now shown as monitoring instead of critical.
- **Clearer Recovery Text**: Summary text now says that recovery mowing is in progress and verification will happen when the mowing session ends.
- **No Premature Recovery Confirmation**: Recovery is still only confirmed by the existing session-confirmation logic; this change only avoids a misleading red state while the robot is actively proving recovery.
- **Robot Sensor State**: Individual robot sensors no longer stay `critical` solely because of `CLEARED_BUT_UNVERIFIED` while the robot is mowing.
- **Regression Coverage**: Adds tests for summary assessment and robot sensor behavior during recovery mowing.

## Improvements in version 0.5.10

- **Service Descriptions**: Adds `services.yaml` for the integration services registered by Automower Supervisor.
- **Cleaner Home Assistant Logs**: Prevents Home Assistant from logging `Failed to load services.yaml for integration: automower_supervisor` when loading service metadata.
- **No Logic Change**: The mower supervision, 08:45 AUTO check, 11:05 late start kick, calendar sync, and stale-data detection remain unchanged from v0.5.9.

## Improvements in version 0.5.9

- **Late Start Kick at 11:05**: If the schedule should have started but a healthy robot has not attempted mowing today, Supervisor sends `AUTO`, waits 10 seconds, then sends `START`.
- **One Robot at a Time**: The late start kick uses the same command lock as other Robonect command sequences, so robots are never commanded all at once.
- **Safe Eligibility Gates**: The late kick only targets online, fresh-data, no-error robots that are still resting and have no active or pending mowing session.
- **Diagnostics**: Adds `late_start_attempted_date`, `late_start_attempted_at`, `late_start_result`, and `late_start_stage`.
- **Regression Coverage**: Adds tests for eligible and ineligible late-start behavior.

## Improvements in version 0.5.8

- **Mower Data Stale Detection**: Robonect clock/heartbeat can no longer hide stale mower-status values.
- **Separate Freshness Metrics**: Adds `mower_data_age_minutes` and `mower_data_stale` so heartbeat freshness and mower data freshness can be diagnosed separately.
- **Attention on Stale Mower Data**: After the daily check has started, stale mower data with no confirmed mowing today becomes `MOWER_DATA_STALE`.
- **Critical Robot Sensor State**: A robot can become `critical` even if `clock_time` continues to update, when actual mower data is stale.
- **Regression Coverage**: Adds a test that ensures fresh clock/heartbeat does not mask stale mower status data.

## Improvements in version 0.5.7

- **Targeted 09:00 Wake-Up**: Evaluates each mower individually and only commands healthy, online robots with fresh data that remain stationary.
- **Minimal Command Sequence**: Sends AUTO first. START is sent only if the mower remains stationary, followed by AUTO to restore automatic mode.
- **One Robot at a Time**: Serializes Robonect commands to reduce REST load and avoid command collisions.
- **Safe Latched-Error Recovery**: For a mower already in Mowing with binary error off but stale Robonect error text, sends STOP → ERROR RESET → START → AUTO with controlled delays.
- **Strict Safety Gates**: No automatic recovery for offline, stale, faulted, stopped, or binary-error-active mowers.
- **One Attempt per Incident/Day**: Morning wake-up is attempted once per mower per day; latched-error recovery once per error incident.
- **Non-Blocking Orchestration**: Long command sequences run as background tasks and do not hold the watchdog.
- **Frequent Calendar Reconciliation**: Rechecks every five minutes from 11:20 through 12:15 on service days.
- **Robonect Startup Ordering**: Adds `after_dependencies: ["robonect"]`.
- **Diagnostics and Tests**: Exposes command stages/results and adds regression tests.

## Improvements in version 0.5.6

- **True Service-Window Worklist**: Problems accumulate across Friday-to-Monday, Monday-to-Wednesday, and Wednesday-to-Friday windows instead of being replaced by each evening's daily state.
- **Morning Reconciliation Every Day**: The configured morning sync checks and persists the shared snapshot on all seven days. On Tuesday, Thursday, Saturday, and Sunday it does not create, update, or delete calendar events.
- **Evening Reconciliation Every Day**: Each evening removes problems proven resolved, retains unresolved earlier problems, adds current problems, and then updates the next service-day event.
- **Same-Day and Persistent Resolution Evidence**: `confirmed_mowing_today` resolves a problem immediately on the same day, while `last_confirmed_mowing_at` and `recovery_verified_at` preserve proof across daily rollover by comparison with the original problem timestamp.
- **Service-Day Final Reconciliation**: Monday, Wednesday, and Friday morning runs perform the final calendar update and delete the event when no problems remain.
- **Charging-Stall Carryover Fix**: `CHARGING_STALLED` remains in the service snapshot while active and is removed only after the charging monitor has cleared it.
- **Window Boundary Reset**: Problems are never carried into a different target service date.
- **Regression Tests**: Adds tests for timestamp-based resolution, current-problem replacement, service-window reset, and non-service-day morning reconciliation without calendar writes.

## Improvements in version 0.5.5

- **Three Service Days**: Calendar worklists are scheduled only for Monday, Wednesday, and Friday. No Automower worklist is created for weekends, Tuesdays, or Thursdays.
- **Accumulated Service Window**: Daily evening syncs maintain one shared worklist for the next service day. Friday-to-Monday, Monday-to-Wednesday, and Wednesday-to-Friday windows are handled automatically.
- **Service-Day Reconciliation**: The 11:20 morning sync performs the final check only on Monday, Wednesday, and Friday, removes resolved robots, and deletes the event entirely if no robots require attention anymore.
- **Safe Google Calendar Replacement**: Calendars without direct `UPDATE_EVENT` support use create-first/delete-old replacement, preserving the old event if creation fails.
- **12:20 Default Start**: New installations default calendar worklists to 12:20, retaining the calendar's existing 30-minute notification behavior.

## Improvements in version 0.5.4

- **Charging Trend Monitoring**: Uses each mower's `sensor.<robot>_mower_status_plain` Simple Status together with the numeric battery sensor to detect a mower that reports `Charging` while battery percentage decreases.
- **False-Alarm Protection**: Samples at least 10 minutes apart and requires two decreasing samples before raising `CHARGING_STALLED`.
- **Automatic Recovery**: Clears the warning when battery percentage rises, charging ends, or battery exceeds 94%.
- **Options Flow Fix**: Removes the obsolete manual `config_entry` assignment that could cause a 500 error when opening integration settings on newer Home Assistant versions.
- **Persistent Diagnostics**: Charging-monitor state survives Home Assistant restarts and is exposed as sensor attributes.

## Improvements in version 0.5.3

- **Consolidated Calendar Safety Release**: Includes the persistent diagnostics from 0.5.1 and the safe in-place calendar update behavior from 0.5.2 in one verified release.
- **Verified Calendar Failure Handling**: Tests cover create, update, and delete failures and confirm that existing managed events are preserved whenever an operation fails.
- **Test Suite Cleanup**: Corrects calendar scenario numbering and updates obsolete `replaced` terminology to the current `updated` result code.
- **Regression Verification**: The full local test suite passes with all 19 tests successful.

## Improvements in version 0.5.2

- **Safe In-Place Calendar Updates**: Existing managed calendar events are updated with Home Assistant's `async_update_event()` when the selected calendar supports `UPDATE_EVENT`.
- **No Delete-Before-Create Risk**: The integration no longer deletes an existing worklist before attempting to replace it. If a safe update is unsupported or fails, the existing calendar event is preserved.
- **Calendar Feature Validation**: Explicitly checks support for `CREATE_EVENT`, `UPDATE_EVENT`, and `DELETE_EVENT` before performing calendar writes.
- **Timezone-Aware Event Data**: Passes timezone-aware `datetime` objects to Home Assistant's calendar layer instead of formatted datetime strings.

## Improvements in version 0.5.1

- **Persistent Calendar Error Diagnostics**: Calendar synchronization errors and missing/unavailable calendar states are saved to persistent storage and remain visible after Home Assistant restarts.
- **Accurate Managed Event Title**: `calendar_event_title` is only exposed when a managed event actually exists in `event_cache`, preventing stale titles after the event has been deleted.
- **Maintenance Release**: Includes the first calendar safety and diagnostics fixes following the initial 0.5.0 calendar release.

## Improvements in version 0.5.0

- **Calendar Worklist Synchronization**: Introduces automatic calendar worklist sync for mowers needing attention.
  - **Evening Sync (20:00 Europe/Stockholm)**: Evaluates all mowers, saves a persistent evening snapshot to storage, and creates/replaces a calendar event in the configured calendar entity for the next day at 12:00–12:30 (local time) with a Swedish rule-based description and title listing affected robots (e.g. `Bot Vv18, Bd17, Sbv14`).
  - **Morning Sync (11:20 Europe/Stockholm)**: Reconciles last night's saved snapshot with current robot states at 11:20:
    - *Activity problems* (did not start, short attempt, uncertain attempt, etc.) are resolved if the robot is online, error-free, and actively mowing or has confirmed activity today.
    - *Recovery problems* (active error, cleared but unverified error) require the robot to be fully `recovered` or have confirmed mowing today.
    - *Offline problems* require the robot to be online, updated within the last 15 minutes, error-free, and actively mowing.
    - *New Critical issues* arising overnight (new errors, offline states) are added dynamically.
    - Resolves and removes robots from the title/description, and deletes the calendar event entirely if no robots require attention anymore.
- **Idempotence & Duplicate Prevention**: Uses a precise description marker line `[AUTOMOWER_SUPERVISOR:v1:YYYY-MM-DD]` to securely find, update, or clean up managed events without affecting user events, even across integration reloads and Home Assistant restarts.
- **Configurable Options Flow**: Adds options to select the `calendar_entity_id` and configure Evening sync time, Morning sync time, Calendar event start time, and Event duration.
- **Graceful Disabled Behavior**: If no calendar entity is selected or calendar is disabled, the integration functions normally without throwing warning banners or repair issues.
- **Manual Services**: Registers `automower_supervisor.sync_calendar` (accepting `auto`, `evening`, or `morning` mode) and `automower_supervisor.delete_managed_calendar_event` for manual reconciliation and debugging.
- **Downtime Catch-up**: Performs startup checks to run missed morning syncs (cutoff: 12:00) or evening syncs (cutoff: midnight) if Home Assistant was offline during the scheduled trigger times.
- **Deterministic Svenska Text Mallar**: Utilizes pure rule-based, deterministic Swedish text formatting. No external LLMs, OAuth, or direct Google Calendar APIs are used (all calls go through Home Assistant's standard calendar services and component layer).

## Improvements in version 0.4.4

- **Robust Pending Confirmation Reason Codes**: Exposes pending reason codes (`PENDING_MOWING_CONFIRMATION`, `CONFIRMATION_PENDING`, `RECOVERY_CONFIRMATION_PENDING`) strictly based on the active runtime pending states, preventing stale historical attempt results from incorrectly generating pending indicators.
- **Diagnostic Pending Normalization & Warnings**: Handles invalid or corrupt pending confirmation types gracefully, exposing them via `PENDING_CONFIRMATION_TYPE_INVALID` for troubleshooting, while keeping daily assessment monitoring stable.

## Improvements in version 0.4.3

- **Date Scoping of Robot Sensor Attempt Warnings**: Scopes individual robotsensor warning states and attempt-based reason codes to the current day. Historical (e.g. yesterday's) attempt results (like short attempt, uncertain attempt, session lost, failed mowing session, etc.) do not cause warning status or diagnostic reason codes to remain active on the sensor today.
- **Diagnostics Attributes**: Exposes a new `last_attempt_is_today` boolean attribute in the robot sensor state to simplify testing and troubleshooting in Home Assistant.
- **Consistent Timestamp Evaluation**: Reuses a single evaluated timestamp across schedule checks, helper functions, and date checks to avoid discrepancies at minute or day boundaries.

## Improvements in version 0.4.2

- **Strict Recovery-Only Categories**: Restricts 5-minute recovery-only verification sessions to cutting, other, or none category errors. Movement errors continue to be recovered exclusively through positive distance accumulation.
- **Robust Scoping of Attempt Results**: Gating daily attention evaluation rules so that historical/yesterday's attempt results (short attempt, uncertain_attempt, failed session, etc.) do not affect today's assessment. Once date changes, only today's session results are parsed. Unresolved errors and offline checks remain active regardless of today's date.
- **Robot Sensor Reason Codes**: Exposes specific reason codes in `assessment_reasons` for pending recovery confirmation (`RECOVERY_CONFIRMATION_PENDING` / `CONFIRMATION_PENDING`), verified recovery session (`RECOVERY_VERIFIED_SESSION`), and invalid recovery (`RECOVERY_CONFIRMATION_INVALID`).
- **Persistent Storage Saving on Backfill**: Guarantees that rehydration backfills or normalization of `pending_confirmation_type` flags are immediately saved to disk.

## Improvements in version 0.4.1

- **Text Status Prioritization in Attention Messages**: Uses plain text status instead of raw numeric codes in all Swedish attention templates (e.g., "Charging (100 %)" instead of "4").
- **Daily Gating Before 11:30**: Gates normal activity warnings (like did not start, short attempts, uncertain attempts, started but not confirmed, etc.) so that they are not assessed before 11:30 local time. Only real critical problems (active errors, cleared but unverified errors, offline state, and error/session-lost events) are flagged before 11:30.
- **Differentiated Recovery and Mowing Thresholds**: Separates recovery verification from full daily confirmed mowing:
  - *Recovery-only verification* requires at least 5 minutes of actual mowing (`RECOVERY_CONFIRM_MIN_MINUTES = 5`) with supporting activity and no errors, which resolves cleared cutting errors.
  - *Full mowing confirmation* still requires at least 10 minutes (`MOWING_CONFIRM_MIN_MINUTES = 10`) with supporting activity and no errors to be counted as confirmed mowing today.
  - Adds the `pending_confirmation_type` attribute (`full_mowing` or `recovery_only`) to represent the confirmation type persistently.
- **Monitoring Ordered List**: The summary sensor's `monitoring_names` attribute matches the exact ordering defined in `ROBOTS`.
