# OrgForge reference files

Vendored from [aeriesec/orgforge](https://github.com/aeriesec/orgforge) at commit `1da5e4b51e22f4a82db4b003becc9cb42cfec34b` under the MIT licence (`LICENSE`).

- `config.yaml` — the simulator configuration that generated the Apex Athletics corpus (company, start date 2026-01-01, org chart, hires and departures). Unmodified; sha256 `d39a6e66ce702d9545b08a9f44e37b5e9356d7ba2d2ea36ec5c5af2fb1d73a4d`.

Constellation reads the org chart from here because the published dataset does not carry it. The access tables ported into `src/constellation/brain/access.py` cite `eval/eval_harness.py` at the same commit, line by line.
