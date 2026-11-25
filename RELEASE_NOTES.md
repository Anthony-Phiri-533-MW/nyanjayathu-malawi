# Release Notes – LakeWatch v0.9.0

## What's new

- **Adapter pattern** – uniform `SensorAdapter` interface for all sensor products (`ChirpsAdapter` initially; other adapters can be added by subclassing).
- **Strategy pattern** – swappable spectral‑index algorithms; `MNDWI_Strategy` registered under key ``water_extent``.
- **Pipeline pattern** – ordered processing chain (`Pipeline`, `PipelineStep`, `PipelineContext`) that coordinates download → window → calibrate → index → quality‑flag → alert.
- **Version tracking** – `backend/_version.py` now supplies ``__version__`` (0.9.0.dev0).
- **Pattern registry** – `backend/app/pattern_registry.py` provides central lookup of adapters and strategies.

## Bug fixes / improvements

- Minor refactoring of the ingestion worker to use the new `Pipeline` instead of linear function calls.
- Added unit‑test scaffolding for the three patterns (see `tests/` folder).

## Upgrading

- No database migration required.
- If you are using the provider registry, the new `SensorAdapter` implementations can be discovered via the `pattern_registry.get_adapter()` function; existing code continues to work unchanged.