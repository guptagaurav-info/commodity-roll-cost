PY ?= python
export PYTHONPATH := src

.PHONY: all ingest run test
all: ingest run
ingest:
	$(PY) -m rollcost.ingest
run:
	$(PY) -m rollcost.pipeline
test:
	$(PY) -m pytest -q tests
