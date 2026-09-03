# Research tooling

Scripts used to build the provider specs and the integration plan. They read/write a scratch directory
(`U3_SCRATCH`, default `~/.u3-scratch`) containing the mirrored vendor docs, reader notes, live-probe samples and prompts.

| script | purpose |
|---|---|
| `zenmux_chat.py` | ZenMux chat helper. Uses the Ultra subscription key (`ZENMUX_API_KEY`) for inference and the management key (`ZENMUX_PLATFORM_API`) to gate on remaining Flow quota, throttle to the plan RPM across processes, and record per-call cost/latency into a ledger. Supports OpenAI and Anthropic protocols and web search. |
| `zenmux_status.py` | Prints subscription quota windows, PAYG balance and ledger totals. |
| `synth.py` | Builds a provider-spec synthesis prompt from reader notes + probe narratives and writes `docs/research/<provider>.md`; `synth.py cross` writes the cross-provider mapping doc. |
| `probe_narrative.py` | Generates a machine narrative (status, headers, JSON structure) from saved probe samples. |
| `op_ws_capture.py` | Captures OddsPapi v5 WebSocket traffic per channel set into JSONL samples. |
| `cross_join.py` | Live cross-provider join probe: OpticOdds↔OddsPapi fixtures via `externalProviders.opticoddsId`, SharpSports via `oddsjamId == OpticOdds game_id` and team+time, bookmaker overlap, side-by-side prices. |
| `plan_panel.py` | Judge-panel planning: four planners (different angles/models) → two judges → final synthesis into `docs/PLAN.md`. |

Required env: `OPTICODDS_API_KEY`, `ODDSPAPI_API_KEY`, `SHARPSPORTS_API_KEY` (public) and `SHARPSPORTS_API_SECRET` (private key; required for `/events` and betPrices endpoints), `ZENMUX_API_KEY`, `ZENMUX_PLATFORM_API`.
