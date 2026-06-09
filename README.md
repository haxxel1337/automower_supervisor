# Automower Supervisor v0.3.1

Automower Supervisor is a local Home Assistant custom integration that aggregates and monitors Husqvarna Automower / Robonect installations. It tracks the health and errors of 11 specific robotic lawn mowers, ensuring that any real errors detected are persistently stored and tracked until verified.

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
