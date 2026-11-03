.PHONY: install run demo test hybrid compare validate headline record-weather osm

install:         ## Python dependencies
	python3 -m pip install -r requirements.txt

run:             ## launch the dashboard: http://127.0.0.1:8000
	python3 -m routetwin

demo:            ## seeded, reproducible run with the scripted storyline, started immediately
	python3 -m routetwin --demo --seed 42

test:
	python3 -m pytest -q

hybrid:          ## real recorded weather + simulated pavement/traffic (run record-weather first)
	ROUTETWIN_OPERATOR_TOKEN=$${ROUTETWIN_OPERATOR_TOKEN:-demo-token} python3 -m routetwin --mode hybrid

compare:         ## maintenance policy comparison on identical simulated environments
	python3 scripts/compare_policies.py --days 180 --seeds 3

validate:        ## estimator validation: filter consistency and model mismatch (about 3 minutes)
	python3 scripts/validate_estimator.py --days 60 --seeds 3

headline:        ## the 30-day demonstration figures quoted in the proposal
	python3 scripts/headline_accuracy.py

record-weather:  ## needs internet
	python3 scripts/record_weather.py 60

osm:             ## needs internet
	python3 scripts/fetch_osm_corridor.py
