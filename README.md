# Automower Supervisor v0.2.0

Automower Supervisor is a local Home Assistant custom integration that aggregates and monitors Husqvarna Automower / Robonect installations. It tracks the health and errors of 11 specific robotic lawn mowers, ensuring that any real errors detected are persistently stored and tracked until verified.

## Features in version 0.2

- **Local Event Monitoring**: Listens to existing robotic lawn mower entities directly in Home Assistant without external polling. Push-based updates are processed in real-time.
- **Periodic Watchdog Check**: A background watchdog runs every 5 minutes (using Home Assistant's `async_track_time_interval`) to check the age of the entity states and detect frozen or stale data without polling any external API or Robonect device.
- **Offline and Stale Data Detection**:
  - `online` is marked `true` when at least one heartbeat entity has updated within 15 minutes.
  - `online` is marked `false` when no heartbeat entity has updated within 60 minutes.
  - If a robot is offline, its state becomes `critical` with reason code `ROBOT_OFFLINE` (and the `source_values_stale` attribute is set to `true`).
  - If updates are older than 15 minutes but <= 60 minutes, the state is `warning` with reason code `STALE_SOURCE_DATA`.
- **Persistent Error Log**: Real errors are captured and written to local storage using Home Assistant's Store helper.
- **Fault Retention**: An error is marked as `cleared_but_unverified` when the mower reports `Fault 0` or goes `off`. It remains in a `critical` assessment state until a future version adds automated verification.
- **Config Flow Setup**: Setup is easily initiated via the Home Assistant UI (Settings -> Devices & Services).
- **11 Robots Monitored**: Monitored robot IDs:
  - `automowerkv5` (Kv5)
  - `automowertuv4` (Tuv4)
  - `automowervv14mini` (Vv14 Mini)
  - `automowervv14big` (Vv14 Big)
  - `automowervv18` (Vv18)
  - `automoweralmv3` (Almv3)
  - `automowerbd17` (Bd17)
  - `automowersbv14` (Sbv14)
  - `automowervv2` (Vv2)
  - `automowertrv4` (Trv4)
  - `automowerlv9` (Lv9)
- **Central Discovery Sensor**: A summary sensor (`sensor.automower_supervisor_discovery`) details the overall integration status and the configuration of expected vs missing/unavailable entities.

## What is NOT included in version 0.2

- No external API/MQTT/REST client connection.
- No Google Calendar integration.
- No automated verification of recovered lawn mowers (transitioning to `recovered`).
- No analysis of battery trends, mowing statistics, or distance.

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
