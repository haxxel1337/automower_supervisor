# Automower Supervisor v0.5.11

Automower Supervisor is a local Home Assistant custom integration that aggregates and monitors Husqvarna Automower / Robonect installations. It tracks the health and errors of 11 specific robotic lawn mowers, ensuring that any real errors detected are persistently stored and tracked until verified.

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
- **Service-Day Reconciliation**: The 11:20 morning sync performs the final check only on Monday, Wednesday, and Friday, removes resolved robots, and deletes the event when no work remains.
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
- **Robust Scoping of Attempt Results**: Gating daily attention evaluation rules so that historical/yesterday's attempt results (short attempt, uncertain attempt, failed session, etc.) do not affect today's assessment. Once date changes, only today's session results are parsed. Unresolved errors and offline checks remain active regardless of today's date.
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

## Improvements in version 0.4.0

- **Daily Attention Assessment**: Adds rule-based daily attention checking for each robot. It begins evaluation at 11:30 local time and makes a final assessment after 18:05.
- **Robust Incomplete Observation Handling**: Handles installations or restarts occurring mid-day by avoiding false `DID_NOT_START` warnings. The robot transitions to a `monitoring` state with `INCOMPLETE_DAILY_OBSERVATION` until a full daily cycle has completed.
- **Summary Attention Sensor**: Registers `sensor.automower_supervisor_summary` which tracks the total count of robots needing attention, lists affected robot IDs/names, and includes a detailed markdown-compatible description.
- **Deterministic Svenska Text Mallar**: Employs pure deterministic Swedish formatting templates for all warnings, states, and diagnostics. No external LLMs are used.
- **Separate Sensor and Attention States**: Robots retain their primary sensor states (`ok`, `warning`, `critical`, `insufficient_data`) separate from their `daily_attention_state` (`not_evaluated`, `normal`, `monitoring`, `needs_attention`).
- **Future Ready**: Google Calendar support is planned for a subsequent release; no calendar API calls are included in this version.

## Improvements in version 0.3.5

- **Automatic Category Backfill**: On startup, when loading persistent storage, any missing, empty, "none", or invalid error categories are automatically recalculated from `last_real_error` using the deterministic `classify_error()` helper.
- **Migration Storage Persistence**: If any migrations or category corrections occur at startup, the updated states are immediately written back to persistent storage.
- **State and Timestamp Preservation**: The startup backfill/migration is purely diagnostic and database-only; it does not change error timestamps (`last_real_error_at`), set `current_error_active`, change the recovery state machine (`recovery_state`), or trigger new error events.

## Improvements in version 0.3.4

- **Evaluation Order on Error**: When a new error occurs, any pending mowing confirmation is resolved *before* the active error state is set.
- **Recovery Verification Preservation**: If a pending session has passed its grace period, it is confirmed first. This allows the previous error recovery to be verified and stored in history, even if the new error immediately places the robot back into an active error state.

## Improvements in version 0.3.3

- **Grace Period Error Evaluation**: Errors occurring within the 5-minute grace period will correctly fail the pending mowing confirmation.
- **Errors After Grace Period**: Errors occurring after the grace period has passed will no longer retroactively fail the session; the pending confirmation is finalized and confirmed first, and the new error is registered separately.
- **Robust Startup and Coexistence**: If a pending confirmation is loaded from storage, it is evaluated prior to initializing new mowing sessions or registering new errors. Corrupted storage states (such as missing or invalid timestamps) are logged as warnings and safely cleared without crashing the integration.

## Improvements in version 0.3.2

- **Text Status Prioritization**: Text status (`current_status_plain` / `mower_status_plain`) is prioritized over numeric status values (which are only used as fallback). This ensures that numeric status codes (like `2` or `7`) are not incorrectly treated as unknown statuses or end active sessions.
- **Persistent Pending Confirmation Coexistence**: Pending confirmations are never cleared or overwritten when a new session starts (including startup observation sessions at Home Assistant startup). The pending confirmation candidate and the active session coexist concurrently.
- **Attempt Metadata Preservation**: Latest attempt metadata (`last_mowing_attempt_at`) is only updated when a session terminates, preventing active sessions from overwriting metadata of past attempts.

## Improvements in version 0.3.1

- **Long-Running Temporary Statuses**: Normal `Searching` and `Detecting status` states now keep the active mowing session open indefinitely without any timeout, only pausing active mowing time accumulation.
- **Definitive Terminating Statuses**: Explicit terminating states like `Searching for charging station` immediately end the session.
- **Resilient Distance delta tracking**: Handles distance sensor resets (e.g. going from 40 to 0) by accumulating only positive deltas, ensuring that resets do not falsely indicate lack of movement or break recovery verification.
- **Separated Pending Confirmations**: Multiple sessions are now confirmed/failed independently. Starting a new mowing session while a previous session is in its 5-minute grace period no longer overrides or clears the pending confirmation candidate.
- **Graceful Unknown Status Fallback**: Okända/icke-kartlagda statusar avslutar inte längre sessionen omedelbart; de sätter bara sessionen i ett tillfälligt pausat/osäkert läge.

## Features in version 0.3

- **Mowing Session Tracking**: Registers cohesive mowing sessions. Distinguishes short startup attempts (faktiska klippförsök < 3 min) from real mowing.
- **Mowing Confirmation & Grace Period**: Evaluates session validity upon termination. Sessions of >= 10 minutes require supporting data (battery drop >= 2, distance delta >= 1.0, or runtime hours delta >= 0.01) to enter a 5-minute confirmation grace period. After 5 minutes without new errors, it is classified as `confirmed_mowing`.
- **Verified Recovery Logic**: Automated verification to recover from previous errors:
  - *Movement errors* (e.g. "No traction") transition from `cleared_but_unverified` to `recovered` immediately upon a distance increase of >= 1.0.
  - *Cutting / other errors* (e.g. "Blade disc blocked") transition to `recovered` after a confirmed mowing session has completed.
- **Stockholm Timezone Schedule Support**: Monitored robots follow a fixed daily schedule (Monday-Sunday 11:00-18:00 Europe/Stockholm). If the schedule is active, warnings are generated if mowing is active but not yet confirmed today, or if a mowing attempt was made but has not yet been confirmed today.
- **Local Event Monitoring**: Listens to existing robotic lawn mower entities directly in Home Assistant without external polling. Push-based updates are processed in real-time.
- **Periodic Watchdog Check**: A background watchdog runs every 5 minutes to check state age and frozen data.
- **Offline and Stale Data Detection with Grace Period**:
  - `online` is marked `true` when at least one heartbeat entity has updated within 15 minutes.
  - If heartbeat entities go `unavailable` or `unknown` temporarily, the watchdog uses a grace period (retaining the online state for up to 60 minutes based on `last_heartbeat_seen_at`) rather than classifying them offline immediately.
  - `online` is marked `false` when no heartbeat updates have been seen for more than 60 minutes.
- **Persistent Error Log**: Real errors are captured and written to local storage using Home Assistant's Store helper.
- **Fault Retention**: An error is marked as `cleared_but_unverified` when the mower reports `Fault 0` or goes `off`. It remains in a `critical` assessment state until verified.
- **Config Flow Setup**: Setup is easily initiated via the Home Assistant UI.
- **11 Robots Monitored**: Monitored robot IDs include Almv3, Kv5, Tuv4, etc.

## What is NOT included in version 0.3

- No external API/MQTT/REST client connection.
- No Google Calendar integration.
- No direct polling of the Robonect device.
- No REST APIs or LLM parsing.

## Installation

1. Copy the `automower_supervisor` folder to your Home Assistant configuration directory under:
   ```text
   /config/custom_components/automower_supervisor/
   ```
2. Restart Home Assistant.
3. In Home Assistant, navigate to:
   **Settings** → **Devices & services** → **Add integration**
4. Search for:
   **Automower Supervisor**
5. Click to install (no configuration fields are required).

## Verification

You can verify the created entities in Home Assistant under **Developer Tools** → **States**.

### Expected Sensors
- `sensor.automower_supervisor_kv5` to `sensor.automower_supervisor_lv9` (one for each of the 11 robots).
  States:
  - `critical`: The robot has an active error, or a previously occurred error is now cleared but unverified (`cleared_but_unverified`).
  - `warning`: No active error exists, but one or more central monitored entities are missing, unavailable, or `unknown` (while having at least 2 usable entities).
  - `insufficient_data`: Fewer than 2 central monitored entities are available (neither missing, unavailable, nor `unknown`).
  - `ok`: No active/unverified errors, and all required entities are present, available, and have active, known values.
- `sensor.automower_supervisor_discovery` (overall integration health, counting discovered entities, missing, unavailable, and `unknown` metrics). Exposes the `entities_unknown` total attribute and includes the detailed status list under `robots`.

## Debug Logging

To enable verbose logging, add the following to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.automower_supervisor: debug
```

## How to Uninstall

1. Go to **Settings** → **Devices & services**.
2. Locate the **Automower Supervisor** integration.
3. Click the three dots menu and select **Delete**.
4. Restart Home Assistant to remove all registered entities.
