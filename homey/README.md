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
- A local **API key** from Homey (Settings, API keys) with these two
  scopes:
  - `homey.device.readonly` to list devices and read their state
  - `homey.device.control` to switch a device on or off

  A third scope, `homey.zone.readonly`, is optional: with it the device list
  and the tile groups show room names.

## Set up

1. Install Homey in **Settings › Plugins**.
2. In **Settings › Content › Web pages & apps**, add Homey.
3. Enter the hub address, for example `http://homey.local`, and the API key.
4. Choose **Test connection**.
5. Choose **Scan** under Devices and pick the devices to show. Only devices that can be switched
   on and off are listed.
6. Save, then place it on a page in **Settings › Dashboard › Pages and regions**.

You can add Homey more than once, each with its own devices, so one hub can serve a kitchen screen
and a hallway screen with different tiles.

## The key and the address

- The key stays on the Calvin server. It is never sent to a browser, and it is
  not written to the log.
- Plain `http://` sends the key unencrypted across your local network, so use
  it only on a network you trust. The plugin never turns certificate checking
  off.
- An https:// address works only with a certificate your devices already trust.
  If your Homey uses its own certificate, use http:// on a network you trust.
- If you change the hub address, Calvin asks for the key again, so a saved key
  is never sent to a new address.
- A tap only works for a device in the chosen list. A device removed from
  Settings stops working at once, even on a screen that still shows its tile.

## Tile messages

| Message | Meaning |
|---|---|
| Not responding | The hub or the device didn't answer. The tile keeps the name and room it last had. |
| Not found in Homey | The device was deleted in Homey. Scan again and pick the devices to show. |
| Couldn't reach Homey. | The hub did not answer. |
| Homey refused the API key. | The key is wrong, or it lacks a scope above. Until the Calvin fix for this ships (branch `fix/switch-grid-errors`), the tile shows "Couldn't reach Homey." instead. |
| Can't be switched from here | The device is no longer in the chosen list. |
| That device isn't available. | The device was deleted since the last refresh. |

A switch can succeed while Calvin cannot read the device back (the hub stopped
answering right after). The tile then shows "Couldn't reach Homey." and goes back
to its old state even though the device switched; the next refresh, within about
15 seconds, shows the real state. When the first read still shows the old value,
Calvin waits a moment and reads once more, and the tile shows what the hub then
reports.

State changes made elsewhere (the Homey app, a wall switch) appear within
about 15 seconds.
