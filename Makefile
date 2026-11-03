PYTHON ?= python3

.PHONY: install run-all run-sales run-api run-quality run-warehouse test clean

install:
	$(PYTHON) -m pip install -r requirements-dev.txt

run-all: run-sales run-api run-quality run-warehouse

run-sales:
	$(PYTHON) 01-sales-data-pipeline/src/pipeline.py

run-api:
	$(PYTHON) 02-api-data-integration/src/api_pipeline.py

run-quality:
	$(PYTHON) 03-data-quality-pipeline/src/quality_pipeline.py --as-of 2024-06-30

run-warehouse:
	$(PYTHON) 04-analytical-data-warehouse/src/warehouse_pipeline.py

test:
	$(PYTHON) -m pytest -q

clean:
	find . -path "*/data/output/*" ! -name ".gitkeep" -type f -delete
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
