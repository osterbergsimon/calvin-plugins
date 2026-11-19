# Homey Pro local API notes

Sources are Athom's public developer documentation only. No hub was contacted.
"Assumed" marks what the documentation does not state; the plugin treats each
of these defensively.

Reference pages:

- Web API welcome page: <https://api.developer.homey.app/> (full text: <https://api.developer.homey.app/llms-full.txt>)
- Devices manager: <https://athombv.github.io/node-homey-api/HomeyAPIV3Local.ManagerDevices.html>
- Device fields: <https://athombv.github.io/node-homey-api/HomeyAPIV3Local.ManagerDevices.Device.html>
- Zones manager: <https://athombv.github.io/node-homey-api/HomeyAPIV3Local.ManagerZones.html>
- Zone fields: <https://athombv.github.io/node-homey-api/HomeyAPIV3Local.ManagerZones.Zone.html>

## Documented

| Fact | Source |
|---|---|
| List devices: `GET /api/manager/devices/device`, scope `homey.device.readonly`, returns an object keyed by device id | Devices manager |
| Read one device: `GET /api/manager/devices/device/:id`, scope `homey.device.readonly` | Devices manager |
| Set a capability: `PUT /api/manager/devices/device/:deviceId/capability/:capabilityId`, scope `homey.device.control`, body fields `value` (string, number or boolean), optional `opts`, optional `transactionId` | Devices manager |
| Device fields: `id`, `name`, `zone` (string), `available` (boolean), `capabilities` (array of ids), `capabilitiesObj` (object) | Device fields |
| List zones: `GET /api/manager/zones/zone`, scope `homey.zone.readonly`, returns an object keyed by zone id; a zone has `id` and `name` | Zones manager, Zone fields |
| Homey calls use `Authorization: Bearer <token>` (documented for session tokens) | Web API welcome page |
| The path prefix is `/api/...` | Devices manager |

## Not documented, assumed

The support article on API keys answers 403 to automated clients, so these
could not be confirmed. Community posts agree with each assumption but are not
official.

| Point | Assumption in this plugin |
|---|---|
| How a local API key is created, and the scope names the app offers | Created in the Homey web app; the README names `homey.device.readonly` and `homey.device.control` (and `homey.zone.readonly` for zone labels) |
| Base URL form and port for a local key | Whatever the user types in the hub address field (`http://` or `https://`); the plugin appends `/api/...` |
| TLS certificate of the local address | Not stated. Certificate verification stays on; the plugin never disables it. A hub without a valid certificate is reached over plain `http://` |
| A local key uses the Bearer header | `Authorization: Bearer <key>` |
| `capabilitiesObj.onoff.value` | A boolean |
| `zone` is a zone id | Resolved through the zone list; if that call fails or the scope is missing, the zone label is left out |
| Status for a bad key or missing scope | 401 and 403 both mean "key refused" |
| Status for an unknown device | 404 means the device is gone |
| Status of a successful `PUT .../capability/onoff` | Any 2xx. The plugin then reads the device back and shows what the hub reports |
| `GET /api/manager/devices/device/:id` | Returns the bare device object (not wrapped), with the same `id` that was asked for; a different `id` is treated as not reachable |
| `available` | A boolean; anything but `true` counts as unavailable |
| Certificate of a local `https://` address | Whether it is one a stock `httpx` trusts is not stated. The plugin uses the default trust store only (`trust_env=False`), so `SSL_CERT_FILE` and similar variables are ignored and a private certificate authority cannot be used |
| Size and text of hub answers | Not stated. Bodies over about 2 MB are treated as not reachable; device and zone names are cut to 80 printable characters; device ids over 256 characters or with control characters are skipped |
| Any other non-2xx, a timeout, a connect error or a body that is not the expected JSON | The hub is treated as not reachable |

## Environment settings

The client is built with `trust_env=False`, so proxy and certificate
environment settings (`SSL_CERT_FILE` and similar) are ignored. A hub whose
certificate comes from a private certificate authority therefore cannot be used
over `https://`; use `http://` on a trusted network.

## Tile message for a refused key

The tile text "Homey refused the API key." appears only once the Calvin fix on
branch `fix/switch-grid-errors` ships; until then the tile shows
"Couldn't reach Homey." and the README says so.
