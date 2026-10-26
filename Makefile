.PHONY: install test demo hybrid compare record-weather osm
PY ?= python3

install:
	$(PY) -m pip install -r requirements.txt

test:
	$(PY) -m pytest -q

demo:            ## deterministic simulation mode with the scripted storyline, http://127.0.0.1:8000
	$(PY) -m routetwin --mode simulation --seed 42

hybrid:          ## real recorded weather + simulated pavement/traffic (run record-weather first)
	ROUTETWIN_OPERATOR_TOKEN=$${ROUTETWIN_OPERATOR_TOKEN:-demo-token} $(PY) -m routetwin --mode hybrid

compare:         ## maintenance policy comparison on identical simulated environments
	$(PY) scripts/compare_policies.py --days 180 --seeds 3

record-weather:  ## needs internet
	$(PY) scripts/record_weather.py 60

osm:             ## needs internet
	$(PY) scripts/fetch_osm_corridor.py
