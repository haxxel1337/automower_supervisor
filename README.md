# Automower Supervisor v0.4.4

Automower Supervisor is a local Home Assistant custom integration that aggregates and monitors Husqvarna Automower / Robonect installations. It tracks the health and errors of 11 specific robotic lawn mowers, ensuring that any real errors detected are persistently stored and tracked until verified.

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
