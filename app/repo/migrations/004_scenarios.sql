-- Preserve every historical event and alert. Existing first alerts also reserve
-- the first-attention slot; never remove duplicate legacy evidence to add an index.
CREATE TRIGGER IF NOT EXISTS first_attention_once
BEFORE INSERT ON alert_outbox
WHEN NEW.kind IN ('HIGH_NEW','MEDIUM_NEW','RAPID_NEW','ACCEL_NEW','BREAKOUT_NEW')
AND EXISTS (SELECT 1 FROM alert_outbox WHERE episode_id=NEW.episode_id
            AND kind IN ('HIGH_NEW','MEDIUM_NEW','RAPID_NEW','ACCEL_NEW','BREAKOUT_NEW'))
BEGIN
    SELECT RAISE(IGNORE);
END;
-- Old payloads had no version; recover it from their immutable event snapshot.
UPDATE episodes SET payload=json_set(payload,'$.rule_version',
  COALESCE((SELECT json_extract(e.payload,'$.rule_version') FROM episode_events e
            WHERE e.episode_id=episodes.episode_id ORDER BY sequence LIMIT 1),
           'spike_rules_v1.0.0'))
WHERE json_extract(payload,'$.rule_version') IS NULL;
