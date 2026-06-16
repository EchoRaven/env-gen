# Cutover 11 Baseline (RunHub)

## Test counts
- regressions: 7 OK
- discover: 443 OK

## Environment
- httpx version: 0.28.1
- docker compose version: Docker Compose version v2.31.0

## Existing surfaces this cutover extends
- HubRegistry init pattern: matches eventhub/codehub/workhub/apihub
  - `self.eventhub = EventHub(self._store_dir)`
  - `self.codehub = CodeHub(self.base_dir, self._store_dir, eventhub=self.eventhub)`
  - `self.workhub = WorkHub(self._store_dir, eventhub=self.eventhub)`
  - `self.apihub = APIHub(self._store_dir, eventhub=self.eventhub)`
- EventHub.publish_event(source_hub, event_type, payload, recipients=, priority=, thread_id=)
- APIHub.get_endpoints() -> {key: endpoint_dict}
- JsonStore: file-locked atomic JSON KV (post-Cutover-9)

## New hub being added
RunHub — 5th sibling of the existing 4 hubs
