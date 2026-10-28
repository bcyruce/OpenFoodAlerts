# Relate Notifications across Sources, never merge them

When Notifications from different Sources appear to describe the same incident (for example a Dutch RASFF notification and an NVWA warning), we record a Relation with the matching method and score instead of merging them into one record. Each Notification keeps its own official fields and provenance, a wrong match costs one bad link rather than corrupted data, and statistics are counted per Source.

## Consequences

- The site cannot show a single deduplicated count of "incidents"; it shows counts per Source and the Relations between them.
- v1 records no Relations at all: RASFF subjects are English and NVWA texts are Dutch, so text similarity cannot match them, and RASFF's public data has no brands. Matching is deferred to v1.1.
