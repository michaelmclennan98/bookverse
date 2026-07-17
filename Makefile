.PHONY: run test check

run:
	streamlit run app.py

test:
	pytest

check:
	python -m compileall app.py bookverse tests
	pytest
