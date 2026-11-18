# Homey

On/off tiles for chosen Homey devices. Each tile shows a device as On, Off or
Not responding, and a tap switches it. Anyone standing at the screen can tap a
tile, so only the devices you pick in Settings can be switched.

<!-- TODO(min-host-version): replace the sentence below with the exact first
Calvin release that contains plugin actions and the switch-grid tile, once it
is published. -->

Requires a Calvin release newer than 0.1.0-rc.3 (the first with plugin actions
and the switch-grid tile). An older Calvin rejects this plugin when it loads.

## What you need

- A **Homey Pro** on your local network. Homey Bridge is not supported: the
  plugin uses the Homey Pro local API, so it keeps working without the internet.
- A local **API key** from the Homey app (Settings, API Keys) with these two
  scopes:
  - `homey.device.readonly` to list devices and read their state
  - `homey.device.control` to switch a device on or off

  A third scope, `homey.zone.readonly`, is optional: with it the device list
  and the tile groups show room names.

## Set up

1. Add the Homey plugin in Calvin Settings.
2. Enter the hub address, for example `http://homey.local`, and the API key.
3. Choose **Test Connection**.
4. Choose **Scan** next to Devices and pick the devices to show. Only devices
   that can be switched on and off are listed.
5. Save, then place the Homey tile on a screen.

Each instance has its own device list, so one hub can serve a kitchen screen
and a hallway screen with different tiles.

## The key and the address

- The key stays on the Calvin server. It is never sent to a browser, and it is
  not written to the log.
- Plain `http://` sends the key unencrypted across your local network, so use
  it only on a network you trust. `https://` works when the hub has a valid
  certificate. The plugin never turns certificate checking off.
- If you change the hub address, Calvin asks for the key again, so a saved key
  is never sent to a new address.
- A tap only works for a device in the chosen list. A device removed from
  Settings stops working at once, even on a screen that still shows its tile.

## Tile messages

| Message | Meaning |
|---|---|
| Couldn't reach Homey | The hub did not answer. |
| Homey refused the API key | The key is wrong, or it lacks a scope above. |
| Can't be switched from here | The device is no longer in the chosen list. |

State changes made elsewhere (the Homey app, a wall switch) appear within
about 15 seconds.
