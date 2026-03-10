PYTHON ?= python

.PHONY: install test cov check clean

install:
	PYTHON=$(PYTHON) bash run install

test:
	PYTHON=$(PYTHON) bash run test

cov:
	PYTHON=$(PYTHON) bash run cov

check: cov

clean:
	bash run clean
