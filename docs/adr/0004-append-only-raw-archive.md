# Keep every raw response forever and re-parse by replay

Every fetched response is stored unchanged in an append-only archive, and parsers are versioned. Fixing a parser means replaying the archive, never refetching. Sources delete and rewrite their records (the RASFF consumer portal drops entries after four weeks; NVWA relaunched its site in 2026), so the archive is the only way to keep history and to reproduce any past state of the data. The cost is storage, which is small at this scale.
